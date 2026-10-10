from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TraceForgeEngine:
    """Minimal evidence-first TRACEFORGE vertical slice.

    v0 supports deterministic acquisition from a local source, provenance capture,
    hash evidence, independent re-verification, graph projection, append-only replay,
    and fail-closed recovery.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.artifacts_dir = self.root / "artifacts"
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.root / "events.jsonl"
        self.state_path = self.root / "state.json"
        self._state = self._load_state()

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"artifacts": {}, "nodes": [], "edges": []}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _save_state(self) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(_canonical(self._state), encoding="utf-8")
        os.replace(tmp, self.state_path)

    def _read_events(self) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        return [
            json.loads(line)
            for line in self.events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def _append_event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        events = self._read_events()
        seq = len(events)
        prev_hash = events[-1]["record_hash"] if events else "0" * 64
        unsigned = {
            "seq": seq,
            "prev_hash": prev_hash,
            "event_type": event_type,
            "payload": payload,
        }
        record_hash = _sha256_bytes(_canonical(unsigned).encode("utf-8"))
        record = {**unsigned, "record_hash": record_hash}
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(_canonical(record) + "\n")
        return record

    def _node(self, node_id: str, node_type: str, status: str, **metadata: Any) -> None:
        if any(node["id"] == node_id for node in self._state["nodes"]):
            return
        self._state["nodes"].append(
            {"id": node_id, "type": node_type, "status": status, "metadata": metadata}
        )

    def _edge(
        self,
        from_id: str,
        relation: str,
        to_id: str,
        status: str = "OBSERVED",
    ) -> None:
        edge = {
            "from": from_id,
            "relation": relation,
            "to": to_id,
            "status": status,
        }
        if edge not in self._state["edges"]:
            self._state["edges"].append(edge)

    def acquire(
        self,
        *,
        query: str,
        source: str | Path,
        route: str,
        failed_routes: list[str] | None = None,
    ) -> dict[str, Any]:
        source_path = Path(source).resolve()
        data = source_path.read_bytes()
        digest = _sha256_bytes(data)
        captured_at = _now()

        source_id = f"SRC-{digest[:16]}"
        artifact_id = f"ART-{digest[:16]}"
        evidence_id = f"EVD-{digest[:16]}"
        trace_id = f"TRC-{uuid.uuid4().hex[:16]}"
        artifact_path = self.artifacts_dir / digest
        if not artifact_path.exists():
            artifact_path.write_bytes(data)

        search_dna = {
            "query": query,
            "route": route,
            "source": str(source_path),
            "timestamp": captured_at,
            "artifact": artifact_id,
            "evidence": evidence_id,
            "verification": "PENDING",
            "related_nodes": [source_id, artifact_id, evidence_id],
            "failed_routes": list(failed_routes or []),
            "successful_routes": [route],
            "recovery_path": str(source_path),
            "confidence": 1.0,
            "freshness": captured_at,
            "reuse_value": None,
        }

        self._state["artifacts"][artifact_id] = {
            "artifact_id": artifact_id,
            "source_id": source_id,
            "trace_id": trace_id,
            "evidence_id": evidence_id,
            "source_path": str(source_path),
            "artifact_path": str(artifact_path),
            "sha256": digest,
            "status": "OBSERVED",
            "search_dna": search_dna,
        }
        self._node(
            trace_id,
            "TRACE",
            "OBSERVED",
            query=query,
            route=route,
            captured_at=captured_at,
        )
        self._node(
            source_id,
            "SOURCE",
            "OBSERVED",
            path=str(source_path),
            sha256=digest,
        )
        self._node(
            artifact_id,
            "ARTIFACT",
            "OBSERVED",
            path=str(artifact_path),
            sha256=digest,
        )
        self._node(
            evidence_id,
            "EVIDENCE",
            "OBSERVED",
            kind="sha256",
            value=digest,
        )
        self._edge(trace_id, "FOUND_BY", artifact_id)
        self._edge(source_id, "PRODUCES", artifact_id)
        self._edge(artifact_id, "SUPPORTED_BY", evidence_id)

        self._append_event(
            "ACQUIRE",
            {
                "trace_id": trace_id,
                "source_id": source_id,
                "artifact_id": artifact_id,
                "evidence_id": evidence_id,
                "sha256": digest,
                "search_dna": search_dna,
            },
        )
        self._save_state()
        return {
            "status": "OBSERVED",
            "trace_id": trace_id,
            "source_id": source_id,
            "artifact_id": artifact_id,
            "evidence_id": evidence_id,
            "artifact_path": str(artifact_path),
            "sha256": digest,
            "search_dna": search_dna,
        }

    def verify(self, artifact_id: str) -> dict[str, Any]:
        meta = self._state["artifacts"][artifact_id]
        artifact_path = Path(meta["artifact_path"])
        source_path = Path(meta["source_path"])
        expected = meta["sha256"]

        if not artifact_path.exists():
            verdict = {
                "status": "BLOCKED",
                "reason": "artifact missing",
                "artifact_id": artifact_id,
            }
            self._append_event("VERIFY_BLOCKED", verdict)
            return verdict

        artifact_hash = _sha256_bytes(artifact_path.read_bytes())
        if artifact_hash != expected:
            verdict = {
                "status": "BLOCKED",
                "reason": "artifact hash mismatch",
                "artifact_id": artifact_id,
                "artifact_hash": artifact_hash,
                "expected_hash": expected,
            }
            self._append_event("VERIFY_BLOCKED", verdict)
            return verdict

        if not source_path.exists():
            verdict = {
                "status": "BLOCKED",
                "reason": "source missing",
                "artifact_id": artifact_id,
            }
            self._append_event("VERIFY_BLOCKED", verdict)
            return verdict

        source_hash = _sha256_bytes(source_path.read_bytes())
        if source_hash != expected:
            verdict = {
                "status": "BLOCKED",
                "reason": "source hash mismatch",
                "artifact_id": artifact_id,
                "source_hash": source_hash,
                "expected_hash": expected,
            }
            self._append_event("VERIFY_BLOCKED", verdict)
            return verdict

        meta["status"] = "VERIFIED"
        meta["search_dna"]["verification"] = "VERIFIED"
        for node in self._state["nodes"]:
            if node["id"] in {artifact_id, meta["evidence_id"]}:
                node["status"] = "VERIFIED"

        verifier_id = "VERIFIER-SHA256"
        self._node(
            verifier_id,
            "VERIFIER",
            "VERIFIED",
            method="sha256/source-byte-equality",
        )
        self._edge(artifact_id, "VERIFIED_BY", verifier_id, "VERIFIED")
        self._append_event(
            "VERIFY",
            {
                "artifact_id": artifact_id,
                "source_hash": source_hash,
                "artifact_hash": artifact_hash,
                "status": "VERIFIED",
            },
        )
        self._save_state()
        return {
            "status": "VERIFIED",
            "reason": "source and artifact hashes match",
            "artifact_id": artifact_id,
            "source_hash": source_hash,
            "artifact_hash": artifact_hash,
        }

    def graph(self) -> dict[str, Any]:
        return {
            "nodes": list(self._state["nodes"]),
            "edges": list(self._state["edges"]),
        }

    def replay(self) -> dict[str, Any]:
        events = self._read_events()
        if not events:
            return {"status": "UNKNOWN", "reason": "no events", "event_count": 0}

        expected_prev = "0" * 64
        for seq, record in enumerate(events):
            if record.get("seq") != seq or record.get("prev_hash") != expected_prev:
                return {
                    "status": "BLOCKED",
                    "reason": "sequence or predecessor mismatch",
                    "event_count": len(events),
                }
            unsigned = {
                "seq": record["seq"],
                "prev_hash": record["prev_hash"],
                "event_type": record["event_type"],
                "payload": record["payload"],
            }
            expected_hash = _sha256_bytes(_canonical(unsigned).encode("utf-8"))
            if record.get("record_hash") != expected_hash:
                return {
                    "status": "BLOCKED",
                    "reason": "record hash mismatch",
                    "event_count": len(events),
                }
            expected_prev = record["record_hash"]

        return {
            "status": "VERIFIED",
            "reason": "event chain verified",
            "event_count": len(events),
            "tip_hash": expected_prev,
        }

    def export_package(self) -> dict[str, Any]:
        package_dir = self.root / "knowledge_package"
        package_dir.mkdir(parents=True, exist_ok=True)
        graph_path = package_dir / "graph.json"
        events_path = package_dir / "events.jsonl"
        manifest_path = package_dir / "manifest.json"

        graph = self.graph()
        replay = self.replay()
        graph_path.write_text(_canonical(graph), encoding="utf-8")
        if self.events_path.exists():
            shutil.copyfile(self.events_path, events_path)
        else:
            events_path.write_text("", encoding="utf-8")

        manifest = {
            "schema_version": "traceforge/v0",
            "created_at": _now(),
            "artifact_count": len(self._state["artifacts"]),
            "trace_count": sum(
                1 for node in self._state["nodes"] if node["type"] == "TRACE"
            ),
            "evidence_count": sum(
                1 for node in self._state["nodes"] if node["type"] == "EVIDENCE"
            ),
            "event_count": replay.get("event_count", 0),
            "event_chain_status": replay["status"],
            "event_tip_hash": replay.get("tip_hash"),
            "graph_sha256": _sha256_bytes(graph_path.read_bytes()),
            "events_sha256": _sha256_bytes(events_path.read_bytes()),
        }
        manifest_path.write_text(_canonical(manifest), encoding="utf-8")
        return {
            "manifest": manifest,
            "manifest_path": str(manifest_path),
            "graph_path": str(graph_path),
            "events_path": str(events_path),
        }

    def recover(self, artifact_id: str) -> dict[str, Any]:
        meta = self._state["artifacts"][artifact_id]
        source_path = Path(meta["source_path"])
        artifact_path = Path(meta["artifact_path"])
        expected = meta["sha256"]

        if not source_path.exists():
            verdict = {
                "status": "BLOCKED",
                "reason": "source missing",
                "artifact_id": artifact_id,
            }
            self._append_event("RECOVERY_BLOCKED", verdict)
            return verdict

        source_data = source_path.read_bytes()
        source_hash = _sha256_bytes(source_data)
        if source_hash != expected:
            verdict = {
                "status": "BLOCKED",
                "reason": "source hash mismatch",
                "artifact_id": artifact_id,
                "source_hash": source_hash,
                "expected_hash": expected,
            }
            self._append_event("RECOVERY_BLOCKED", verdict)
            return verdict

        tmp = artifact_path.with_suffix(".recovering")
        tmp.write_bytes(source_data)
        recovered_hash = _sha256_bytes(tmp.read_bytes())
        if recovered_hash != expected:
            tmp.unlink(missing_ok=True)
            verdict = {
                "status": "BLOCKED",
                "reason": "recovered hash mismatch",
                "artifact_id": artifact_id,
                "recovered_hash": recovered_hash,
                "expected_hash": expected,
            }
            self._append_event("RECOVERY_BLOCKED", verdict)
            return verdict

        os.replace(tmp, artifact_path)
        recovery_trace_id = f"TRC-{uuid.uuid4().hex[:16]}"
        self._node(
            recovery_trace_id,
            "TRACE",
            "VERIFIED",
            operation="RECOVERY",
            source=str(source_path),
        )
        self._edge(
            artifact_id,
            "RECOVERED_FROM",
            recovery_trace_id,
            "VERIFIED",
        )
        self._append_event(
            "RECOVERY",
            {
                "artifact_id": artifact_id,
                "recovery_trace_id": recovery_trace_id,
                "recovered_hash": recovered_hash,
                "status": "VERIFIED",
            },
        )
        self._save_state()
        return {
            "status": "VERIFIED",
            "reason": "artifact recovered from provenance route",
            "artifact_id": artifact_id,
            "recovered_hash": recovered_hash,
            "artifact_path": str(artifact_path),
        }
