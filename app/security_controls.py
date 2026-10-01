"""Production safety controls: freshness, redaction, provenance markers and market checks."""
from __future__ import annotations
import hashlib, hmac, os, re, time
from dataclasses import dataclass
from typing import Any

SENSITIVE_KEY_RE=re.compile(r"(api[_-]?key|access[_-]?token|auth|authorization|password|passwd|secret|private[_-]?key|cookie|set-cookie|session|ssn|iban|credit[_-]?card|card[_-]?number)",re.I)
SECRET_VALUE_RE=re.compile(r"(?i)\b(sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]{8,}|AKIA[0-9A-Z]{12,}|Bearer\s+[A-Za-z0-9._~+/-]{8,})\b")
EMAIL_RE=re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",re.I)
PHONE_RE=re.compile(r"(?<!\d)(?:\+\d[\d ()-]{7,}\d)(?!\d)")
REDACTED="[REDACTED]"

def redact(value:Any)->Any:
    if isinstance(value,dict):
        return {str(k): (REDACTED if SENSITIVE_KEY_RE.search(str(k)) else redact(v)) for k,v in value.items()}
    if isinstance(value,list): return [redact(v) for v in value]
    if isinstance(value,str):
        value=SECRET_VALUE_RE.sub(REDACTED,value)
        value=EMAIL_RE.sub(lambda m:m.group(0)[0]+"***@"+m.group(0).split("@",1)[1],value)
        value=PHONE_RE.sub(lambda m:m.group(0)[:3]+"***"+m.group(0)[-2:],value)
        return value
    return value

def provenance_marker(tenant_id:str, seq:int, prev_hash:str, payload_json:str)->str:
    secret=os.getenv("OLA_PROVENANCE_SECRET","")
    material=f"{tenant_id}|{seq}|{prev_hash}|{payload_json}".encode()
    return (hmac.new(secret.encode(),material,hashlib.sha256) if secret else hashlib.sha256(material)).hexdigest()

@dataclass(frozen=True)
class Freshness:
    status:str
    age_seconds:float
    max_age_seconds:float
    source:str
    observed_at:float
    def as_dict(self): return {"status":self.status,"age_seconds":round(self.age_seconds,3),"max_age_seconds":self.max_age_seconds,"source":self.source,"observed_at":self.observed_at}

def check_freshness(observed_at:float,max_age_seconds:float,source:str)->Freshness:
    now=time.time(); age=max(0.0,now-float(observed_at))
    return Freshness("FRESH" if age<=max_age_seconds else "STALE",age,float(max_age_seconds),source,float(observed_at))

@dataclass(frozen=True)
class MarketComparison:
    status:str
    reference_price:float
    observed_prices:tuple[float,...]
    currency:str
    tolerance_pct:float
    spread_pct:float
    reason:str

def compare_market_price(observed:float,references:list[float],currency:str,tolerance_pct:float=10.0)->MarketComparison:
    if not references or observed<0 or any(p<0 for p in references): return MarketComparison("REVIEW",float(observed),tuple(references),currency,tolerance_pct,100.0,"insufficient market references")
    median=sorted(references)[len(references)//2] if len(references)%2 else (sorted(references)[len(references)//2-1]+sorted(references)[len(references)//2])/2
    spread=(max(references)-min(references))/median*100 if median else 0.0
    deviation=abs(observed-median)/median*100 if median else (0.0 if observed==0 else 100.0)
    if spread>tolerance_pct: return MarketComparison("REVIEW",median,tuple(references),currency,tolerance_pct,spread,"market sources conflict")
    return MarketComparison("PASS" if deviation<=tolerance_pct else "REVIEW",median,tuple(references),currency,tolerance_pct,spread,"within tolerance" if deviation<=tolerance_pct else "observed price outside tolerance")

def require_freshness(observed_at:float,max_age_seconds:float,source:str)->dict:
    result=check_freshness(observed_at,max_age_seconds,source)
    return result.as_dict()
