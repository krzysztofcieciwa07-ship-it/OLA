from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from .database import SessionLocal
from .hashchain import canonical_json
from .models import StateCheckpoint


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _state_dir() -> Path:
    path = Path(os.getenv("OLA_STATE_DIR", ".ola_state"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_hash(payload: dict, previous_hash: str) -> str:
    material = canonical_json({"previous_hash": previous_hash, "payload": payload})
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def persist_checkpoint(
    *,
    tenant_id: str,
    run_id: str,
    stage: str,
    status: str,
    artifact: dict,
    metadata: dict | None = None,
) -> dict:
    metadata = metadata or {}
    with SessionLocal() as db:
        previous = db.scalar(
            select(StateCheckpoint)
            .where(StateCheckpoint.tenant_id == tenant_id, StateCheckpoint.run_id == run_id)
            .order_by(StateCheckpoint.sequence.desc())
        )
        sequence = 0 if previous is None else previous.sequence + 1
        previous_hash = "0" * 64 if previous is None else previous.state_hash

    payload = {
        "tenant_id": tenant_id,
        "run_id": run_id,
        "sequence": sequence,
        "stage": stage,
        "status": status,
        "artifact": artifact,
        "metadata": metadata,
        "timestamp": _utc_now(),
    }
    state_hash = _state_hash(payload, previous_hash)
    checkpoint_id = hashlib.sha256(
        canonical_json({"run_id": run_id, "sequence": sequence, "state_hash": state_hash}).encode()
    ).hexdigest()[:32]

    run_dir = _state_dir() / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    final_path = run_dir / f"{sequence:04d}-{stage}.json"
    document = {
        "schema": "ola.state-checkpoint.v1",
        "checkpoint_id": checkpoint_id,
        "previous_hash": previous_hash,
        "state_hash": state_hash,
        **payload,
    }
    raw = canonical_json(document).encode("utf-8")

    fd, temp_name = tempfile.mkstemp(prefix=".checkpoint-", dir=run_dir)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, final_path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)

    artifact_hash = _sha256_bytes(raw)
    with SessionLocal() as db:
        row = StateCheckpoint(
            id=checkpoint_id,
            tenant_id=tenant_id,
            run_id=run_id,
            sequence=sequence,
            stage=stage,
            status=status,
            artifact_path=str(final_path),
            artifact_sha256=artifact_hash,
            previous_hash=previous_hash,
            state_hash=state_hash,
            payload_json=canonical_json(document),
        )
        db.add(row)
        db.commit()

    return {
        "checkpoint_id": checkpoint_id,
        "sequence": sequence,
        "stage": stage,
        "status": status,
        "artifact_path": str(final_path),
        "artifact_sha256": artifact_hash,
        "previous_hash": previous_hash,
        "state_hash": state_hash,
    }


def verify_run_state(tenant_id: str, run_id: str) -> dict:
    with SessionLocal() as db:
        rows = db.scalars(
            select(StateCheckpoint)
            .where(StateCheckpoint.tenant_id == tenant_id, StateCheckpoint.run_id == run_id)
            .order_by(StateCheckpoint.sequence.asc())
        ).all()

    if not rows:
        return {"status": "UNKNOWN", "reason": "no state checkpoints", "checkpoints": 0}

    expected_previous = "0" * 64
    for expected_sequence, row in enumerate(rows):
        if row.sequence != expected_sequence:
            return {"status": "BLOCK", "reason": "checkpoint sequence gap", "checkpoints": len(rows)}
        if row.previous_hash != expected_previous:
            return {"status": "BLOCK", "reason": "checkpoint predecessor mismatch", "checkpoints": len(rows)}
        path = Path(row.artifact_path)
        if not path.is_file():
            return {"status": "BLOCK", "reason": "checkpoint artifact missing", "checkpoints": len(rows)}
        raw = path.read_bytes()
        if _sha256_bytes(raw) != row.artifact_sha256:
            return {"status": "BLOCK", "reason": "checkpoint artifact hash mismatch", "checkpoints": len(rows)}
        document = json.loads(raw)
        if document.get("state_hash") != row.state_hash:
            return {"status": "BLOCK", "reason": "checkpoint state hash mismatch", "checkpoints": len(rows)}
        expected_previous = row.state_hash

    return {
        "status": "STABLE",
        "reason": "checkpoint sequence, paths, artifacts and state hashes are consistent",
        "checkpoints": len(rows),
        "last_state_hash": expected_previous,
    }


def recover_latest_checkpoint(tenant_id: str, run_id: str) -> dict:
    verification = verify_run_state(tenant_id, run_id)
    if verification["status"] != "STABLE":
        return verification
    with SessionLocal() as db:
        row = db.scalar(
            select(StateCheckpoint)
            .where(StateCheckpoint.tenant_id == tenant_id, StateCheckpoint.run_id == run_id)
            .order_by(StateCheckpoint.sequence.desc())
        )
    document = json.loads(Path(row.artifact_path).read_text(encoding="utf-8"))
    return {
        "status": "RECOVERED",
        "checkpoint_id": row.id,
        "sequence": row.sequence,
        "stage": row.stage,
        "state": document,
        "artifact_path": row.artifact_path,
        "artifact_sha256": row.artifact_sha256,
    }
