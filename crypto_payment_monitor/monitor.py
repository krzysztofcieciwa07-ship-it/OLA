"""Polling monitor for configured BTC addresses and EVM native/ERC-20 transfers.

Keyless, read-only. Requires configured HTTPS providers and explicit watchlists.
""" 
from __future__ import annotations
import json, os, time
from pathlib import Path
from typing import Any
from .evm import EVMRPC
from .bitcoin import Esplora
from .config import Config

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

def _topic_address(address: str) -> str:
    if not address.startswith("0x") or len(address) != 42:
        raise ValueError("invalid EVM address")
    return "0x" + address[2:].lower()

def _address_topic(address: str) -> str:
    return "0x" + "0"*24 + address[2:].lower()

class Ledger:
    """Append-only JSONL event store; local persistence, no secrets."""
    def __init__(self, path: str = "monitor-events.jsonl"):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.seen=set()
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                try: self.seen.add(json.loads(line)["event_id"])
                except (ValueError, KeyError): continue
    def append_once(self, event: dict[str,Any]) -> bool:
        eid=event["event_id"]
        if eid in self.seen: return False
        with self.path.open("a",encoding="utf-8") as f:
            f.write(json.dumps(event,sort_keys=True)+"\n")
        self.seen.add(eid); return True

class Monitor:
    def __init__(self, config: Config, ledger: Ledger):
        config.validate(); self.config=config; self.ledger=ledger
        self.watch_btc=[a.strip() for a in os.getenv("BTC_WATCH_ADDRESSES", "").split(",") if a.strip()]
        self.watch_evm=[_topic_address(a.strip()) for a in os.getenv("EVM_WATCH_ADDRESSES", "").split(",") if a.strip()]
        self.tokens={}
        # Token config format: TOKEN_SYMBOL=contract; explicit addresses only.
        for entry in os.getenv("ERC20_TOKEN_CONTRACTS", "").split(","):
            if not entry.strip(): continue
            symbol,contract=entry.split("=",1)
            self.tokens[symbol.strip().upper()]=_topic_address(contract.strip())
        self.rpc=EVMRPC(config.ethereum_rpc_url, config.ethereum_chain_id) if config.ethereum_rpc_url else None
        self.esplora=Esplora(config.bitcoin_esplora_url) if config.bitcoin_esplora_url else None
    def scan_btc(self) -> list[dict]:
        if not self.esplora: return []
        emitted=[]
        for address in self.watch_btc:
            for tx in self.esplora.address_transactions(address):
                txid=tx.get("txid")
                if not txid: continue
                for index,vout in enumerate(tx.get("vout", [])):
                    if vout.get("scriptpubkey_address") != address: continue
                    value=int(vout.get("value",0))
                    if value<=0: continue
                    status=tx.get("status",{})
                    event={"event_id":f"btc:{txid}:{index}","chain":"bitcoin","asset":"BTC","tx_hash":txid,"recipient":address,"amount_base_units":value,"block_height":status.get("block_height"),"confirmed":bool(status.get("confirmed")),"status":"confirmed" if status.get("confirmed") else "observed","observed_at":int(time.time())}
                    if self.ledger.append_once(event): emitted.append(event)
        return emitted
    def scan_erc20(self) -> list[dict]:
        if not self.rpc or not self.watch_evm or not self.tokens: return []
        emitted=[]; head=int(self.rpc.call("eth_blockNumber",[]),16)
        # scan a bounded recent window; operator should set history window.
        start=max(0,head-int(os.getenv("EVM_SCAN_BLOCKS", "500")))
        for symbol,contract in self.tokens.items():
            for recipient in self.watch_evm:
                logs=self.rpc.call("eth_getLogs",[{"fromBlock":hex(start),"toBlock":hex(head),"address":contract,"topics":[TRANSFER_TOPIC,None,_address_topic(recipient)]}])
                for log in logs:
                    tx=log.get("transactionHash"); idx=int(log.get("logIndex","0x0"),16); block=int(log.get("blockNumber","0x0"),16)
                    raw=int(log.get("data","0x0"),16)
                    event={"event_id":f"evm:{self.config.ethereum_chain_id}:{tx}:{idx}","chain":"ethereum","chain_id":self.config.ethereum_chain_id,"asset":symbol,"contract":contract,"tx_hash":tx,"log_index":idx,"recipient":recipient,"amount_base_units":raw,"block_height":block,"status":"observed","observed_at":int(time.time())}
                    if self.ledger.append_once(event): emitted.append(event)
        return emitted
    def scan_native_eth(self) -> list[dict]:
        if not self.rpc or not self.watch_evm: return []
        emitted=[]; head=int(self.rpc.call("eth_blockNumber",[]),16)
        start=max(0,head-int(os.getenv("EVM_SCAN_BLOCKS","500")))
        # inspect block transactions for watched recipients (bounded window)
        for height in range(start,head+1):
            block=self.rpc.call("eth_getBlockByNumber",[hex(height),True])
            if not block: continue
            for tx in block.get("transactions",[]):
                recipient=tx.get("to")
                if not recipient or recipient.lower() not in self.watch_evm: continue
                value=int(tx.get("value","0x0"),16)
                if value<=0: continue
                txid=tx.get("hash")
                event={"event_id":f"eth:{self.config.ethereum_chain_id}:{txid}","chain":"ethereum","chain_id":self.config.ethereum_chain_id,"asset":"ETH","tx_hash":txid,"recipient":recipient,"amount_base_units":value,"block_height":height,"status":"observed","observed_at":int(time.time())}
                if self.ledger.append_once(event): emitted.append(event)
        return emitted
    def scan_once(self) -> list[dict]:
        return self.scan_btc()+self.scan_native_eth()+self.scan_erc20()
