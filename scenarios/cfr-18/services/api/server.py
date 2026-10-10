import json, os, sqlite3, uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

DB=os.environ.get('DB_PATH','/data/flowai.db'); PORT=int(os.environ.get('PORT','8080'))

def now(): return datetime.now(timezone.utc).isoformat()
def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def init():
    os.makedirs(os.path.dirname(DB),exist_ok=True)
    c=db(); c.executescript(open('/app/services/db/init.sql').read()); c.commit(); c.close()

class H(BaseHTTPRequestHandler):
    def send_json(self,status,obj):
        b=json.dumps(obj).encode(); self.send_response(status); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        p=urlparse(self.path).path
        if p=='/health': return self.send_json(200,{'status':'ok'})
        if p=='/api/workflows':
            c=db(); rows=[dict(x) for x in c.execute('SELECT * FROM workflows ORDER BY id DESC LIMIT 100')]; c.close(); return self.send_json(200,rows)
        if p.startswith('/api/job/'):
            try: jid=int(p.rsplit('/',1)[1])
            except ValueError: return self.send_json(400,{'error':'bad id'})
            c=db(); row=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone(); c.close(); return self.send_json(200,dict(row) if row else {'error':'not found'}) if row else self.send_json(404,{'error':'not found'})
        return self.send_json(404,{'error':'not found'})
    def do_POST(self):
        if self.path!='/api/generate': return self.send_json(404,{'error':'not found'})
        n=int(self.headers.get('Content-Length','0')); raw=self.rfile.read(n) if n else b'{}'
        try: body=json.loads(raw)
        except Exception: body={}
        wid=str(uuid.uuid4()); c=db(); ts=now(); cur=c.execute('INSERT INTO jobs(user_id,workflow_id,status,attempts,created_at) VALUES(?,?,?,?,?)',(1,wid,'queued',0,ts)); jid=cur.lastrowid; c.commit(); c.close(); return self.send_json(202,{'job_id':jid,'workflow_id':wid})

init(); ThreadingHTTPServer(('0.0.0.0',PORT),H).serve_forever()
