"""Freshness policy registry for external evidence."""
from dataclasses import dataclass
import time

@dataclass(frozen=True)
class SourceFreshnessPolicy:
    source:str
    max_age_seconds:int

class FreshnessRegistry:
    def __init__(self,policies:dict[str,int]|None=None):
        self._policies=policies or {"market":300,"exchange_rate":300,"web":900,"document":3600}
    def policy(self,source:str)->SourceFreshnessPolicy:
        if source not in self._policies: raise KeyError("unknown freshness policy")
        return SourceFreshnessPolicy(source,self._policies[source])
    def evaluate(self,source:str,observed_at:float)->dict:
        p=self.policy(source); age=max(0,time.time()-float(observed_at))
        return {"source":source,"observed_at":float(observed_at),"age_seconds":age,"max_age_seconds":p.max_age_seconds,"status":"FRESH" if age<=p.max_age_seconds else "STALE"}
