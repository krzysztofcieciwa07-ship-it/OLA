"""Independent clean replay of the CFR-18 worker recovery contract."""
import importlib.util
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_worker():
    spec = importlib.util.spec_from_file_location("worker_replay", ROOT / "services/worker/worker.py")
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    return worker


def run_cycle(worker, db_path):
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    c.executescript((ROOT / "services/db/init.sql").read_text())
    c.execute("INSERT INTO jobs(user_id,workflow_id,status,attempts,created_at) VALUES(1,'replay-seed','processing',1,'2026-01-01')")
    c.commit()
    worker.recover_uncertain(c)
    first = c.execute("SELECT status FROM jobs").fetchone()[0]
    assert first == "queued"
    row = c.execute("SELECT * FROM jobs").fetchone()
    worker.process(c, row)
    job = c.execute("SELECT status,attempts FROM jobs").fetchone()
    count = c.execute("SELECT COUNT(*) FROM workflows WHERE workflow_id='replay-seed'").fetchone()[0]
    events = [r[0] for r in c.execute("SELECT type FROM events ORDER BY id")]
    c.close()
    return {"recovered_from": first, "status": job["status"], "attempts": job["attempts"], "effects": count, "events": events}


def main():
    import os
    import tempfile
    worker = load_worker()
    with tempfile.TemporaryDirectory() as d:
        results = [run_cycle(worker, Path(d) / f"clean-{i}.db") for i in (1, 2)]
    assert results[0] == results[1], results
    assert results[0]["status"] == "done" and results[0]["attempts"] == 2
    assert results[0]["effects"] == 1
    assert "recovery_requeued" in results[0]["events"]
    out = {"source_sha": os.environ["SOURCE_SHA"], "scope": "two isolated SQLite clean replays",
           "deterministic_replay": "PASS", "cycles": results,
           "independent_igor": "NOT_VERIFIED", "docker_replay": "NOT_VERIFIED"}
    Path("evidence/clean-replay.json").write_text(json.dumps(out, sort_keys=True, indent=2) + "\n")
    print(json.dumps(out, sort_keys=True))


if __name__ == "__main__":
    main()
