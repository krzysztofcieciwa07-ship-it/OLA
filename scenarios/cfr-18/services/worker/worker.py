import os, sqlite3, time
from datetime import datetime, timezone
DB=os.environ.get('DB_PATH','/data/flowai.db'); VAR=os.environ.get('FAULT_VARIANT','double_process')

def now(): return datetime.now(timezone.utc).isoformat()
def db(): c=sqlite3.connect(DB,timeout=5); c.row_factory=sqlite3.Row; return c

def process(c,row):
    jid=row['id']; c.execute("UPDATE jobs SET status='processing', attempts=attempts+1, started_at=? WHERE id=?",(now(),jid)); c.commit()
    time.sleep(0.15)
    if VAR=='silent_loss': return
    if VAR=='reactivation': c.execute("INSERT INTO events(type,job_id,created_at) VALUES('reactivation_queued',?,?)",(jid,now()))
    c.execute("INSERT INTO workflows(user_id,workflow_id,created_at) VALUES(?,?,?)",(row['user_id'],row['workflow_id'],now()))
    c.execute("UPDATE jobs SET status='done', finished_at=? WHERE id=?",(now(),jid)); c.commit()

while True:
    try:
        c=db(); rows=c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY id LIMIT 5").fetchall()
        for row in rows: process(c,row)
        c.close(); time.sleep(0.1)
    except Exception as e:
        print(f'worker error: {e}',flush=True); time.sleep(1)
