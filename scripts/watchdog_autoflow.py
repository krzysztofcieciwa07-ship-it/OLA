#!/usr/bin/env python3
"""Source-bound fail-closed audit of recent real 12h runtime runs; no mutation."""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

SHA = re.compile(r"[a-f0-9]{40}\Z")
FAILED = {"failure", "timed_out", "startup_failure", "action_required"}
DONE = FAILED | {"success", "cancelled", "skipped", "neutral"}
ACTIVE = {"queued", "in_progress", "waiting", "requested", "pending"}

class BadRun(ValueError):
    pass

def classify(rows, source_sha):
    if not SHA.fullmatch(source_sha):
        raise BadRun("invalid main SOURCE_SHA")
    if not isinstance(rows, list) or len(rows) > 30:
        raise BadRun("invalid/oversized run list")
    seen=set(); parsed=[]
    for row in rows:
        if not isinstance(row, dict):raise BadRun("non-object run")
        rid, sha = row.get("databaseId"), row.get("headSha")
        status, conclusion = row.get("status"), row.get("conclusion")
        if type(rid) is not int or rid <= 0 or rid in seen:
            raise BadRun("missing/duplicate run id")
        seen.add(rid)
        if not isinstance(sha, str) or not SHA.fullmatch(sha):
            raise BadRun("invalid run source SHA")
        if status not in ACTIVE|{"completed"}:
            raise BadRun("unknown run status")
        if status == "completed" and conclusion not in DONE:
            raise BadRun("missing/invalid completed conclusion")
        # gh CLI may serialize a nonterminal conclusion as null or empty string.
        if status in ACTIVE and conclusion not in (None, ""):
            raise BadRun("active run has conclusion")
        if sha == source_sha:
            parsed.append({"id":rid,"sha":sha,"status":status,"conclusion":conclusion})
    active = [r for r in parsed if r["status"] in ACTIVE]
    done = [r for r in parsed if r["status"] == "completed"]
    if len(done) >= 2 and all(r["conclusion"] in FAILED for r in done[:2]):
        return {"status":"BLOCKED","reason":"two_latest_completed_failed","latest_run_ids":[r["id"] for r in done[:2]],"source_sha":source_sha,"production_go":"NO-GO"}
    if done and done[0]["conclusion"] in FAILED:
        return {"status":"DEGRADED","reason":"latest_completed_failed","latest_run_ids":[done[0]["id"]],"source_sha":source_sha,"production_go":"NO-GO"}
    if active:
        return {"status":"PENDING","reason":"autoflow_in_progress","latest_run_ids":[r["id"] for r in active],"source_sha":source_sha,"production_go":"NO-GO"}
    if done and done[0]["conclusion"] == "success":
        return {"status":"WATCHDOG_HEALTHY","reason":"latest_completed_succeeded","latest_run_ids":[done[0]["id"]],"source_sha":source_sha,"production_go":"NO-GO"}
    if not parsed:
        return {"status":"BOOTSTRAP","reason":"no_runs_for_current_sha","latest_run_ids":[],"source_sha":source_sha,"production_go":"NO-GO"}
    return {"status":"BLOCKED","reason":"latest_run_not_verified","latest_run_ids":[r["id"] for r in done[:1]],"source_sha":source_sha,"production_go":"NO-GO"}

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--runs-file",type=Path,required=True)
    parser.add_argument("--source-sha",required=True)
    args=parser.parse_args(argv)
    try:
        result=classify(json.loads(args.runs_file.read_text(encoding="utf-8")),args.source_sha)
    except (BadRun,OSError,ValueError) as exc:
        result={"status":"BLOCKED","reason":"input_invalid","detail":str(exc),"production_go":"NO-GO"}
    print(json.dumps(result,sort_keys=True),flush=True)
    return 1 if result["status"]=="BLOCKED" else 0

if __name__=="__main__":sys.exit(main())
