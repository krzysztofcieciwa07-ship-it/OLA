#!/usr/bin/env python3
"""Offline verifier for redacted production DB/log JSONL exports. No DB/network access."""
import argparse, json, secrets, sys
from pathlib import Path
FIELDS=("event_id","tenant_id","record_id","sequence","record_hash","producer_id","outcome")
def load(path):
 rows=[]
 for n,line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(),1):
  if not line.strip(): continue
  try: row=json.loads(line)
  except Exception as e: raise ValueError(f"{path}:{n}: invalid JSON: {e}")
  if not isinstance(row,dict): raise ValueError(f"{path}:{n}: expected JSON object")
  rows.append(row)
 return rows
def index(rows,label):
 out={}
 for r in rows:
  key=r.get("event_id")
  if not key: raise ValueError(f"{label}: missing event_id")
  if key in out: raise ValueError(f"{label}: duplicate event_id {key!r}")
  out[key]=r
 return out
def main():
 ap=argparse.ArgumentParser(description=__doc__)
 ap.add_argument("--db-jsonl",required=True); ap.add_argument("--logs-jsonl",required=True)
 ap.add_argument("--sample-size",type=int,default=100); ap.add_argument("--manifest",default="sample_manifest.json")
 ap.add_argument("--timestamp-tolerance-seconds",type=float,default=5.0)
 args=ap.parse_args()
 if args.sample_size<0: ap.error("--sample-size must be >= 0")
 db=index(load(args.db_jsonl),"DB"); logs=index(load(args.logs_jsonl),"LOG")
 db_ids=set(db); log_ids=set(logs); missing_logs=sorted(db_ids-log_ids); orphan_logs=sorted(log_ids-db_ids); common=sorted(db_ids&log_ids)
 if args.sample_size==0 or args.sample_size>=len(common): sample=common
 else: sample=[common[i] for i in sorted(secrets.SystemRandom().sample(range(len(common)),args.sample_size))]
 mismatches=[]
 for eid in sample:
  a,b=db[eid],logs[eid]; diff={f:{"db":a.get(f),"log":b.get(f)} for f in FIELDS if a.get(f)!=b.get(f)}
  try:
   ta,tb=float(a["timestamp"]),float(b["timestamp"])
   if abs(ta-tb)>args.timestamp_tolerance_seconds: diff["timestamp_delta_seconds"]={"db":ta,"log":tb,"delta":abs(ta-tb),"tolerance":args.timestamp_tolerance_seconds}
  except (KeyError,TypeError,ValueError): diff["timestamp"]={"error":"missing or invalid timestamp"}
  if diff: mismatches.append({"event_id":eid,"differences":diff})
 manifest={"sample_size":len(sample),"db_population":len(db),"log_population":len(logs),"sample_ids":sample,"sampling_method":"secrets.SystemRandom; sampled from common IDs; population reconciliation still required","timestamp_tolerance_seconds":args.timestamp_tolerance_seconds,"mismatch_count":len(mismatches),"mismatches":mismatches,"missing_log_ids":missing_logs,"orphan_log_ids":orphan_logs,"consistency_sample_pass":not mismatches,"population_reconciliation_pass":not missing_logs and not orphan_logs}
 Path(args.manifest).write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n",encoding="utf-8")
 print(json.dumps({k:manifest[k] for k in ("db_population","log_population","sample_size","mismatch_count","consistency_sample_pass","population_reconciliation_pass")},indent=2))
 return 2 if mismatches or missing_logs or orphan_logs else 0
if __name__=="__main__": sys.exit(main())
