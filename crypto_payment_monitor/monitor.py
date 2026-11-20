"""Read-only, keyless BTC/EVM payment observer with bounded RPC requests and durable cursor state."""
from __future__ import annotations
import json, os, time
from pathlib import Path
from typing import Any
from .evm import EVMRPC
from .bitcoin import Esplora
from .config import Config

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

def _topic_address(address: str) -> str:
    if not isinstance(address, str) or not address.startswith("0x") or len(address) != 42:
        raise ValueError("invalid EVM address")
    try: int(address[2:], 16)
    except ValueError as exc: raise ValueError("invalid EVM address") from exc
    return "0x" + address[2:].lower()

def _address_topic(address: str) -> str:
    return "0x" + "0"*24 + _topic_address(address)[2:]

class Ledger:
    """Append-only JSONL event store with event-ID deduplication."""
    def __init__(self, path: str = "monitor-events.jsonl"):
        self.path=Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        self.seen=set()
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try: self.seen.add(json.loads(line)["event_id"])
                except (ValueError, KeyError, TypeError): continue
    def append_once(self, event: dict[str,Any]) -> bool:
        eid=event["event_id"]
        if eid in self.seen: return False
        with self.path.open("a",encoding="utf-8") as f:
            f.write(json.dumps(event,sort_keys=True)+"\n"); f.flush(); os.fsync(f.fileno())
        self.seen.add(eid); return True
    def append_transition(self, event: dict[str,Any]) -> None:
        """Append state transitions; transition IDs include state and observation time."""
        transition=dict(event)
        transition["event_id"]=event["event_id"]+":state:"+str(event["status"])+":"+str(event.get("block_height"))
        self.append_once(transition)

class Monitor:
    def __init__(self, config: Config, ledger: Ledger, state_path: str|None=None):
        config.validate(); self.config=config; self.ledger=ledger
        self.state_path=Path(state_path or (str(ledger.path)+".state.json"))
        self.state=self._load_state()
        self.watch_btc=[a.strip() for a in os.getenv("BTC_WATCH_ADDRESSES", "").split(",") if a.strip()]
        self.watch_evm=[_topic_address(a.strip()) for a in os.getenv("EVM_WATCH_ADDRESSES", "").split(",") if a.strip()]
        self.tokens={}
        for entry in os.getenv("ERC20_TOKEN_CONTRACTS", "").split(","):
            if not entry.strip(): continue
            if "=" not in entry: raise ValueError("token entries must be SYMBOL=CONTRACT")
            symbol,contract=entry.split("=",1); symbol=symbol.strip().upper()
            if not symbol or symbol in self.tokens: raise ValueError("duplicate or empty token symbol")
            self.tokens[symbol]=_topic_address(contract.strip())
        self.rpc=EVMRPC(config.ethereum_rpc_url, config.ethereum_chain_id) if config.ethereum_rpc_url else None
        self.esplora=Esplora(config.bitcoin_esplora_url) if config.bitcoin_esplora_url else None
    def _load_state(self):
        if self.state_path.exists():
            try:
                data=json.loads(self.state_path.read_text(encoding="utf-8"))
                if isinstance(data,dict): return data
            except (ValueError,OSError): pass
        return {}
    def _save_state(self):
        tmp=self.state_path.with_suffix(self.state_path.suffix+".tmp")
        tmp.write_text(json.dumps(self.state,sort_keys=True),encoding="utf-8")
        os.replace(tmp,self.state_path)
    def _emit(self,event):
        if self.ledger.append_once(event): return event
        return None
    def scan_btc(self) -> list[dict]:
        if not self.esplora: return []
        emitted=[]; tip=self.esplora.tip_height()
        for address in self.watch_btc:
            for tx in self.esplora.address_transactions_paginated(address):
                txid=tx.get("txid")
                if not txid: continue
                status=tx.get("status",{}); block_height=status.get("block_height")
                conf=(tip-block_height+1) if status.get("confirmed") and block_height else 0
                for index,vout in enumerate(tx.get("vout",[])):
                    if vout.get("scriptpubkey_address") != address: continue
                    value=int(vout.get("value",0))
                    if value<=0: continue
                    base={"event_id":f"btc:{txid}:{index}","chain":"bitcoin","asset":"BTC","tx_hash":txid,"recipient":address,"amount_base_units":value,"block_height":block_height,"confirmed":conf>=self.config.confirmations_btc,"confirmations":conf,"status":"confirmed" if conf>=self.config.confirmations_btc else ("confirming" if conf else "detected"),"observed_at":int(time.time())}
                    if self._emit(base): emitted.append(base)
                    else: self.ledger.append_transition(base)
        return emitted
    def _evm_scan_range(self, start, end):
        emitted=[]
        # Native transfers: block scans bounded by configurable chunk size.
        watched=set(self.watch_evm)
        for height in range(start,end+1):
            block=self.rpc.call("eth_getBlockByNumber",[hex(height),True])
            if not block: continue
            for tx in block.get("transactions",[]):
                recipient=tx.get("to")
                if not recipient or recipient.lower() not in watched: continue
                value=int(tx.get("value","0x0"),16)
                if value<=0: continue
                receipt=self.rpc.get_receipt(tx.get("hash"))
                if not receipt or receipt.get("status") not in ("0x1","0x01"): continue
                base={"event_id":f"eth:{self.config.ethereum_chain_id}:{tx['hash']}","chain":"ethereum","chain_id":self.config.ethereum_chain_id,"asset":"ETH","tx_hash":tx["hash"],"recipient":recipient.lower(),"amount_base_units":value,"block_height":height,"block_hash":block.get("hash"),"status":"confirmed","confirmations":self.config.confirmations_eth,"observed_at":int(time.time())}
                if self._emit(base): emitted.append(base)
        for symbol,contract in self.tokens.items():
            for recipient in self.watch_evm:
                logs=self.rpc.call("eth_getLogs",[{"fromBlock":hex(start),"toBlock":hex(end),"address":contract,"topics":[TRANSFER_TOPIC,None,_address_topic(recipient)]}])
                for log in logs:
                    tx=log.get("transactionHash"); idx=int(log.get("logIndex","0x0"),16); block=int(log.get("blockNumber","0x0"),16)
                    raw=int(log.get("data","0x0"),16)
                    if raw<=0: continue
                    base={"event_id":f"evm:{self.config.ethereum_chain_id}:{tx}:{idx}","chain":"ethereum","chain_id":self.config.ethereum_chain_id,"asset":symbol,"contract":contract,"tx_hash":tx,"log_index":idx,"recipient":recipient,"amount_base_units":raw,"block_height":block,"block_hash":log.get("blockHash"),"status":"detected","observed_at":int(time.time())}
                    if self._emit(base): emitted.append(base)
        return emitted
    def scan_evm(self) -> list[dict]:
        if not self.rpc or not self.watch_evm: return []
        head=int(self.rpc.call("eth_blockNumber",[]),16)
        confirmed_head=max(0,head-self.config.confirmations_eth+1)
        cursor_key="evm_cursor"
        cursor=int(self.state.get(cursor_key,max(0,confirmed_head-int(os.getenv("EVM_SCAN_BLOCKS","500")))))
        chunk=int(os.getenv("EVM_SCAN_CHUNK","100"))
        if chunk<1 or chunk>1000: raise ValueError("EVM_SCAN_CHUNK must be 1..1000")
        emitted=[]
        while cursor<=confirmed_head:
            end=min(cursor+chunk-1,confirmed_head)
            emitted.extend(self._evm_scan_range(cursor,end))
            cursor=end+1; self.state[cursor_key]=cursor; self._save_state()
        # Confirmation state reconciliation on known events is deliberately separate from event ingestion.
        return emitted
    def scan_once(self) -> list[dict]:
        return self.scan_btc()+self.scan_evm()
