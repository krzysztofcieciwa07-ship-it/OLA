"""Read-only Esplora adapter with paginated address history."""
import json, urllib.request

class Esplora:
    def __init__(self, endpoint: str):
        if not isinstance(endpoint,str) or not endpoint.startswith("https://"): raise ValueError("HTTPS endpoint required")
        self.endpoint=endpoint.rstrip("/")
    def _get(self,path):
        req=urllib.request.Request(self.endpoint+path,headers={"Accept":"application/json"})
        with urllib.request.urlopen(req,timeout=15) as response:
            raw=response.read(2_000_000)
        return json.loads(raw)
    def address_transactions(self,address:str)->list[dict]:
        data=self._get(f"/address/{address}/txs")
        if not isinstance(data,list): raise ValueError("unexpected Esplora response")
        return data
    def address_transactions_paginated(self,address:str,max_pages:int=1000)->list[dict]:
        out=self.address_transactions(address); seen={x.get("txid") for x in out if x.get("txid")}
        pages=1
        while len(out)>=25 and pages<max_pages:
            last=out[-1].get("txid")
            if not last: break
            data=self._get(f"/address/{address}/txs/chain/{last}")
            if not isinstance(data,list): raise ValueError("unexpected Esplora pagination response")
            fresh=[x for x in data if x.get("txid") and x["txid"] not in seen]
            if not fresh: break
            out.extend(fresh); seen.update(x["txid"] for x in fresh); pages+=1
        if pages>=max_pages and len(out)>=25: raise RuntimeError("Esplora pagination safety limit reached")
        return out
    def tip_height(self)->int:
        value=self._get("/blocks/tip/height")
        if not isinstance(value,int) or value<0: raise ValueError("invalid Esplora tip height")
        return value
