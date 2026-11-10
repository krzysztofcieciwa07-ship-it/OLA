"""Independent Docker daemon event observer for one-shot worker lifecycle proofs."""

import hashlib
import json
import subprocess
from dataclasses import dataclass
from typing import Any, Callable

from ..canonical import canonical_json


@dataclass(frozen=True, slots=True)
class DockerEventProof:
    status: str
    reason: str | None
    container_id: str
    image_digest: str
    started_at: float | None
    died_at: float | None
    exit_code: int | None
    events_digest: str | None
    events: tuple[dict[str, Any], ...]


class DockerEventObserver:
    """Read the daemon event stream in a separate docker/podman CLI process."""

    def __init__(self, runtime_binary="docker", runner: Callable[..., Any] | None = None):
        self.runtime_binary = runtime_binary
        self.runner = runner or subprocess.run

    @staticmethod
    def _event_time(event):
        value = event.get("timeNano")
        if type(value) is int and value > 0:
            return value / 1_000_000_000
        value = event.get("time")
        if type(value) in (int, float) and value > 0:
            return float(value)
        return None

    @staticmethod
    def _event_id(event):
        actor = event.get("Actor") or {}
        return actor.get("ID") or event.get("id") or event.get("ID")

    @staticmethod
    def _event_action(event):
        return str(event.get("Action") or event.get("status") or "").lower()

    @staticmethod
    def _event_attributes(event):
        actor = event.get("Actor") or {}
        return actor.get("Attributes") or event.get("Attributes") or {}

    def collect(self, *, since: float, until: float):
        if (
            type(since) not in (int, float)
            or type(until) not in (int, float)
            or since <= 0
            or until <= since
        ):
            raise ValueError("invalid Docker event time window")
        command = [
            self.runtime_binary,
            "events",
            "--since",
            str(max(0, int(since - 5))),
            "--until",
            str(int(until + 5)),
            "--filter",
            "type=container",
            "--format",
            "{{json .}}",
        ]
        try:
            result = self.runner(
                command,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.SubprocessError, TimeoutError):
            raise RuntimeError("docker_event_stream_unavailable") from None
        if result.returncode != 0:
            raise RuntimeError("docker_event_stream_unavailable")
        events = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                raise RuntimeError("docker_event_stream_invalid") from None
            if not isinstance(event, dict):
                raise RuntimeError("docker_event_stream_invalid")
            events.append(event)
        return tuple(events)

    def verify_lifecycle(
        self,
        *,
        container_id: str,
        image_digest: str,
        supervisor_started_at: float,
        supervisor_finished_at: float,
        expected_exit_code: int,
    ) -> DockerEventProof:
        try:
            events = self.collect(
                since=supervisor_started_at,
                until=supervisor_finished_at,
            )
        except (RuntimeError, ValueError) as exc:
            return DockerEventProof(
                "BLOCKED", str(exc), container_id, image_digest,
                None, None, None, None, (),
            )

        matched = tuple(event for event in events if self._event_id(event) == container_id)
        by_action = {}
        for event in matched:
            by_action.setdefault(self._event_action(event), []).append(event)
        required = {"create", "start", "die", "destroy"}
        if not required.issubset(by_action):
            return DockerEventProof(
                "BLOCKED", "docker_event_lifecycle_incomplete", container_id,
                image_digest, None, None, None, None, matched,
            )

        start_event = min(by_action["start"], key=lambda item: self._event_time(item) or 0)
        die_event = max(by_action["die"], key=lambda item: self._event_time(item) or 0)
        started_at = self._event_time(start_event)
        died_at = self._event_time(die_event)
        attributes = self._event_attributes(die_event)
        raw_exit_code = attributes.get("exitCode")
        try:
            exit_code = int(raw_exit_code)
        except (TypeError, ValueError):
            exit_code = None

        if started_at is None or died_at is None or started_at >= died_at:
            reason = "docker_event_time_invalid"
        elif started_at < supervisor_started_at - 10 or died_at > supervisor_finished_at + 10:
            reason = "docker_event_outside_supervisor_window"
        elif exit_code != expected_exit_code:
            reason = "docker_event_exit_code_mismatch"
        else:
            reason = None

        digest = hashlib.sha256(
            canonical_json(sorted(
                matched,
                key=lambda item: self._event_time(item) or 0,
            )).encode("utf-8")
        ).hexdigest()
        return DockerEventProof(
            "VERIFIED" if reason is None else "BLOCKED",
            reason,
            container_id,
            image_digest,
            started_at,
            died_at,
            exit_code,
            digest,
            matched,
        )
