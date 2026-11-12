import json
from subprocess import CompletedProcess

from app.provenance.docker_events import DockerEventObserver


CONTAINER_ID = "c" * 64
IMAGE_DIGEST = "sha256:" + "a" * 64
LABELS = {
    "ola.image.digest": IMAGE_DIGEST,
    "ola.source.commit": "b" * 40,
    "ola.run.id": "00000000-0000-4000-8000-000000000041",
    "ola.agent.id": "hermes-01",
    "ola.agent.instance_id": "00000000-0000-4000-8000-000000000042",
}


def _event(action, timestamp, attributes=None):
    return {
        "Type": "container",
        "Action": action,
        "Actor": {
            "ID": CONTAINER_ID,
            "Attributes": attributes or {},
        },
        "timeNano": int(timestamp * 1_000_000_000),
    }


def _runner_for(events):
    output = "\n".join(json.dumps(event) for event in events)

    def runner(args, **kwargs):
        assert args[:2] == ["docker", "events"]
        assert "--since" in args and "--until" in args
        return CompletedProcess(args, 0, stdout=output, stderr="")

    return runner


def test_docker_event_observer_verifies_actual_container_lifecycle_and_exit_code():
    events = [
        _event("create", 101, LABELS),
        _event("start", 102),
        _event("die", 103, {"exitCode": "0"}),
        _event("destroy", 104),
    ]
    observer = DockerEventObserver(runner=_runner_for(events))

    proof = observer.verify_lifecycle(
        container_id=CONTAINER_ID,
        image_digest=IMAGE_DIGEST,
        supervisor_started_at=100,
        supervisor_finished_at=105,
        expected_exit_code=0,
        expected_labels=LABELS,
    )

    assert proof.status == "VERIFIED"
    assert proof.started_at == 102
    assert proof.died_at == 103
    assert proof.exit_code == 0
    assert len(proof.events_digest) == 64


def test_docker_event_observer_blocks_missing_lifecycle_events():
    events = [
        _event("create", 101, LABELS),
        _event("start", 102),
        _event("destroy", 104),
    ]
    observer = DockerEventObserver(runner=_runner_for(events))

    proof = observer.verify_lifecycle(
        container_id=CONTAINER_ID,
        image_digest=IMAGE_DIGEST,
        supervisor_started_at=100,
        supervisor_finished_at=105,
        expected_exit_code=0,
        expected_labels=LABELS,
    )

    assert proof.status == "BLOCKED"
    assert proof.reason == "docker_event_lifecycle_incomplete"


def test_docker_event_observer_blocks_exit_code_and_identity_label_mismatch():
    events = [
        _event("create", 101, {**LABELS, "ola.agent.id": "different-agent"}),
        _event("start", 102),
        _event("die", 103, {"exitCode": "1"}),
        _event("destroy", 104),
    ]
    observer = DockerEventObserver(runner=_runner_for(events))

    proof = observer.verify_lifecycle(
        container_id=CONTAINER_ID,
        image_digest=IMAGE_DIGEST,
        supervisor_started_at=100,
        supervisor_finished_at=105,
        expected_exit_code=0,
        expected_labels=LABELS,
    )

    assert proof.status == "BLOCKED"
    assert proof.reason == "docker_event_container_labels_mismatch"
