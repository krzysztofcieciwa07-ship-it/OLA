#!/usr/bin/env python3
import argparse, os, random
from pathlib import Path

def mutation(seed):
    r=random.Random(seed)
    return {'kill_delay_ms':r.randint(50,2000),'queue_depth':r.randint(3,15),'restart_count':r.randint(1,4),'fault_variant':r.choice(['double_process','double_process','silent_loss','reactivation']),'penalty_multiplier':round(r.uniform(.8,1.2),2)}

def main():
    p=argparse.ArgumentParser(); p.add_argument('--seed',default=os.environ.get('USER_SEED','default')); p.add_argument('--apply',action='store_true'); p.add_argument('--show-variant',action='store_true'); a=p.parse_args(); m=mutation(a.seed)
    if a.show_variant: print(m['fault_variant']); return
    if a.apply:
        Path('.env.mutation').write_text('\n'.join(f'{k.upper()}={v}' for k,v in m.items())+'\n'); print('.env.mutation written'); return
    print(m)
if __name__=='__main__': main()
