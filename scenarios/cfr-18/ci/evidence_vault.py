#!/usr/bin/env python3
import hashlib, json, os, sys
from datetime import datetime, timezone
from pathlib import Path

VAULT_DIR=Path(os.environ.get('EVIDENCE_DIR','evidence'))
CHAIN_FILE=VAULT_DIR/'.chain.jsonl'
GENESIS=hashlib.sha256(b'CFR-18-GENESIS').hexdigest()

def _last_hash():
    if not CHAIN_FILE.exists(): return GENESIS
    lines=[x for x in CHAIN_FILE.read_text().splitlines() if x.strip()]
    if not lines: return GENESIS
    try: return json.loads(lines[-1])['hash']
    except Exception: return GENESIS

def append(entry_type,payload):
    VAULT_DIR.mkdir(parents=True,exist_ok=True)
    entry={'ts':datetime.now(timezone.utc).isoformat(),'type':entry_type,'payload':payload,'prev_hash':_last_hash()}
    entry['hash']=hashlib.sha256(json.dumps(entry,sort_keys=True).encode()).hexdigest()
    with CHAIN_FILE.open('a') as f: f.write(json.dumps(entry,sort_keys=True)+'\n')
    return entry['hash']

def verify_chain():
    if not CHAIN_FILE.exists(): return {'valid':False,'entries':0,'broken_at':None,'reason':'chain file missing'}
    lines=[x for x in CHAIN_FILE.read_text().splitlines() if x.strip()]
    if not lines: return {'valid':False,'entries':0,'broken_at':None,'reason':'chain file empty'}
    prev=GENESIS
    for i,line in enumerate(lines):
        try: entry=json.loads(line)
        except json.JSONDecodeError as e: return {'valid':False,'entries':len(lines),'broken_at':i,'reason':str(e)}
        stored=entry.pop('hash',None)
        if stored is None: return {'valid':False,'entries':len(lines),'broken_at':i,'reason':'missing hash'}
        if entry.get('prev_hash')!=prev: return {'valid':False,'entries':len(lines),'broken_at':i,'reason':'prev_hash mismatch'}
        computed=hashlib.sha256(json.dumps(entry,sort_keys=True).encode()).hexdigest()
        if computed!=stored: return {'valid':False,'entries':len(lines),'broken_at':i,'reason':'content hash mismatch — tampered'}
        prev=stored
    return {'valid':True,'entries':len(lines),'broken_at':None,'reason':'ok'}

def get_session_start():
    if CHAIN_FILE.exists():
        for line in CHAIN_FILE.read_text().splitlines():
            try:
                e=json.loads(line)
                if e.get('type')=='session_start': return datetime.fromisoformat(e['ts'])
            except Exception: pass
    return datetime.now(timezone.utc)

def main():
    import argparse
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='cmd')
    a=sub.add_parser('append'); a.add_argument('type'); a.add_argument('payload')
    sub.add_parser('verify'); sub.add_parser('dump'); sub.add_parser('session-start')
    args=p.parse_args()
    if args.cmd=='append': print(append(args.type,json.loads(args.payload)))
    elif args.cmd=='verify':
        r=verify_chain(); print(json.dumps(r,indent=2)); sys.exit(0 if r['valid'] else 1)
    elif args.cmd=='dump':
        if CHAIN_FILE.exists(): print(CHAIN_FILE.read_text(),end='')
    elif args.cmd=='session-start': print(append('session_start',{'seed':os.environ.get('USER_SEED','default')}))
    else: p.print_help(); sys.exit(1)
if __name__=='__main__': main()
