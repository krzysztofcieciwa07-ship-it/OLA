"""CFR-18 worker. Recovery is opt-in; never replay an uncertain job blindly."""
import os
import sqlite3
import time
from datetime import datetime, timezone

DB = os.environ.get("DB_PATH", "/data/flowai.db")
VAR = os.environ.get("FAULT_VARIANT", "double_process")
RECOVER = os.environ.get("RECOVER_STALE_PROCESSING", "0") == "1"


def now():
    return datetime.now(timezone.utc).isoformat()


def db():
    c = sqlite3.connect(DB, timeout=5)
    c.row_factory = sqlite3.Row
    return c


def recover_uncertain(c):
    """Reconcile durable side effects before re-queueing interrupted work."""
    c.execute("BEGIN IMMEDIATE")
    for row in c.execute("SELECT * FROM jobs WHERE status='processing'").fetchall():
        existing = c.execute(
            "SELECT COUNT(*) FROM workflows WHERE user_id=? AND workflow_id=?",
            (row["user_id"], row["workflow_id"]),
        ).fetchone()[0]
        if existing == 1:
            c.execute("UPDATE jobs SET status='done', finished_at=? WHERE id=?",
                      (now(), row["id"]))
            event = "recovery_existing_effect"
        elif existing == 0:
            c.execute("UPDATE jobs SET status='queued' WHERE id=?", (row["id"],))
            event = "recovery_requeued"
        else:
            # Ambiguous side effects are quarantined, never executed again.
            c.execute("UPDATE jobs SET status='blocked' WHERE id=?", (row["id"],))
            event = "recovery_blocked_duplicate_effect"
        c.execute("INSERT INTO events(type,job_id,created_at) VALUES(?,?,?)",
                  (event, row["id"], now()))
    c.commit()


def process(c, row):
    jid = row["id"]
    c.execute("BEGIN IMMEDIATE")
    claimed = c.execute(
        "UPDATE jobs SET status='processing', attempts=attempts+1, started_at=? "
        "WHERE id=? AND status='queued'", (now(), jid)
    ).rowcount
    c.commit()
    if claimed != 1:
        return

    time.sleep(0.15)
    if VAR == "silent_loss":
        return

    c.execute("BEGIN IMMEDIATE")
    existing = c.execute(
        "SELECT COUNT(*) FROM workflows WHERE user_id=? AND workflow_id=?",
        (row["user_id"], row["workflow_id"]),
    ).fetchone()[0]
    if existing:
        # Even a stale/duplicate delivery must not repeat the side effect.
        c.execute("UPDATE jobs SET status=?, finished_at=? WHERE id=?",
                  ("done" if existing == 1 else "blocked", now(), jid))
        c.execute("INSERT INTO events(type,job_id,created_at) VALUES(?,?,?)",
                  ("duplicate_delivery_blocked", jid, now()))
    else:
        if VAR == "reactivation":
            c.execute("INSERT INTO events(type,job_id,created_at) VALUES(?,?,?)",
                      ("reactivation_queued", jid, now()))
        c.execute("INSERT INTO workflows(user_id,workflow_id,created_at) VALUES(?,?,?)",
                  (row["user_id"], row["workflow_id"], now()))
        c.execute("UPDATE jobs SET status='done', finished_at=? WHERE id=?",
                  (now(), jid))
    c.commit()


def main():
    recovered = False
    while True:
        try:
            c = db()
            if RECOVER and not recovered:
                recover_uncertain(c)
                recovered = True
            rows = c.execute(
                "SELECT * FROM jobs WHERE status='queued' ORDER BY id LIMIT 5"
            ).fetchall()
            for row in rows:
                process(c, row)
            c.close()
            time.sleep(0.1)
        except Exception as e:
            print(f"worker error: {e}", flush=True)
            time.sleep(1)


if __name__ == "__main__":
    main()
