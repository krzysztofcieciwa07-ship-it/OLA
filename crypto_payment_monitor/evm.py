"""Read-only EVM JSON-RPC client with bounded response size and chain check."""
import json, urllib.request
from typing import Any
class EVMRPC:
    def __init__(self,endpoint:str,expected_chain_id:int):
        if not endpoint.startswith("https://"): raise ValueError("HTTPS endpoint required")
        self.endpoint=endpoint; self.expected_chain_id=expected_chain_id; self._validate_chain()
    def call(self,method:str,params:list[Any])->Any:
        payload=json.dumps({"jsonrpc":"2.0","id":1,"method":method,"params":params}).encode()
        req=urllib.request.Request(self.endpoint,data=payload,headers={"Content-Type":"application/json"})
        with urllib.request.urlopen(req,timeout=15) as response:
            raw=response.read(4_000_000)
        result=json.loads(raw)
        if not isinstance(result,dict): raise ValueError("invalid JSON-RPC response")
        if result.get("error"): raise RuntimeError(f"RPC error: {result['error']}")
        if "result" not in result: raise ValueError("JSON-RPC response missing result")
        return result["result"]
    def _validate_chain(self):
        chain_id=int(self.call("eth_chainId",[]),16)
        if chain_id!=self.expected_chain_id: raise ValueError(f"chain ID mismatch: expected {self.expected_chain_id}, got {chain_id}")
    def get_receipt(self,tx_hash:str): return self.call("eth_getTransactionReceipt",[tx_hash])
