"""Deterministic CFR-18 recovery invariants, isolated from the infinite worker loop."""
import importlib.util
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_worker():
    spec = importlib.util.spec_from_file_location(
        "cfr18_worker", ROOT / "services/worker/worker.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare_db(tmp_path):
    path = tmp_path / "flowai.db"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript((ROOT / "services/db/init.sql").read_text())
    return conn


def insert_job(c, workflow_id, status="processing"):
    c.execute(
        "INSERT INTO jobs(user_id,workflow_id,status,attempts,created_at) "
        "VALUES(1,?,?,1,'2026-01-01T00:00:00Z')",
        (workflow_id, status),
    )
    c.commit()


def test_interrupted_without_effect_is_requeued(tmp_path):
    worker = load_worker()
    c = prepare_db(tmp_path)
    insert_job(c, "lost")
    worker.recover_uncertain(c)
    assert c.execute("SELECT status FROM jobs").fetchone()[0] == "queued"
    assert c.execute("SELECT type FROM events").fetchone()[0] == "recovery_requeued"


def test_interrupted_with_existing_effect_is_not_reexecuted(tmp_path):
    worker = load_worker()
    c = prepare_db(tmp_path)
    insert_job(c, "already")
    c.execute(
        "INSERT INTO workflows(user_id,workflow_id,created_at) "
        "VALUES(1,'already','2026-01-01T00:00:00Z')"
    )
    c.commit()
    worker.recover_uncertain(c)
    assert c.execute("SELECT status FROM jobs").fetchone()[0] == "done"
    assert c.execute("SELECT COUNT(*) FROM workflows").fetchone()[0] == 1


def test_ambiguous_duplicate_effect_blocks_reexecution(tmp_path):
    worker = load_worker()
    c = prepare_db(tmp_path)
    insert_job(c, "duplicate")
    c.executemany(
        "INSERT INTO workflows(user_id,workflow_id,created_at) "
        "VALUES(1,'duplicate','2026-01-01T00:00:00Z')",
        [(), ()],
    )
    c.commit()
    worker.recover_uncertain(c)
    assert c.execute("SELECT status FROM jobs").fetchone()[0] == "blocked"
    assert c.execute("SELECT COUNT(*) FROM workflows").fetchone()[0] == 2
    assert c.execute("SELECT type FROM events").fetchone()[0] == "recovery_blocked_duplicate_effect"
