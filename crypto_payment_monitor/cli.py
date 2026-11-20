"""Single-shot monitor CLI."""
import argparse, json
from .config import Config
from .monitor import Monitor, Ledger

def main():
    p=argparse.ArgumentParser(description="Read-only crypto payment observer")
    p.add_argument("--ledger",default="monitor-events.jsonl")
    args=p.parse_args()
    c=Config(); c.validate()
    m=Monitor(c,Ledger(args.ledger))
    events=m.scan_once()
    print(json.dumps({"new_events":events,"count":len(events)},indent=2))
if __name__=="__main__": main()
