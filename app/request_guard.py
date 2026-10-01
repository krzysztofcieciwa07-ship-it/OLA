"""Small dependency-free API attack surface guard."""
from __future__ import annotations
import threading,time
from dataclasses import dataclass

@dataclass
class _Bucket:
    started:float
    count:int

class RequestGuard:
    def __init__(self,limit:int=60,window_seconds:int=60,max_body_bytes:int=1_048_576):
        self.limit=limit; self.window=window_seconds; self.max_body_bytes=max_body_bytes; self._lock=threading.Lock(); self._buckets:dict[str,_Bucket]={}
    def allow(self,client_id:str,now:float|None=None)->bool:
        now=time.time() if now is None else now
        with self._lock:
            b=self._buckets.get(client_id)
            if b is None or now-b.started>=self.window:
                self._buckets[client_id]=_Bucket(now,1); return True
            if b.count>=self.limit:return False
            b.count+=1; return True
    def body_allowed(self,content_length:str|None)->bool:
        if not content_length:return True
        try:return 0<=int(content_length)<=self.max_body_bytes
        except ValueError:return False
