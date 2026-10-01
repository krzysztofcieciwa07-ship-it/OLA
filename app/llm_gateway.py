"""Provider-neutral, fail-closed LLM gateway for OLA di-OS.

LLM output is RECEIVED evidence, never VERIFIED evidence. Only the evidence
verification chain may promote a result to VERIFIED.
"""
from dataclasses import dataclass
import hashlib, json, os
from urllib.parse import urlparse
import httpx

OPENAI_COMPATIBLE={"openai":("OPENAI_API_KEY","https://api.openai.com/v1"),"openrouter":("OPENROUTER_API_KEY","https://openrouter.ai/api/v1"),"mistral":("MISTRAL_API_KEY","https://api.mistral.ai/v1"),"groq":("GROQ_API_KEY","https://api.groq.com/openai/v1"),"together":("TOGETHER_API_KEY","https://api.together.xyz/v1"),"deepseek":("DEEPSEEK_API_KEY","https://api.deepseek.com/v1"),"xai":("XAI_API_KEY","https://api.x.ai/v1")}
SPECIALIZED={"anthropic","gemini"}; LOCAL={"ollama"}; MAX_RESPONSE_BYTES=2*1024*1024

@dataclass(frozen=True)
class ProviderConfig:
    provider:str; model:str; base_url:str; api_key_env:str|None
@dataclass(frozen=True)
class LLMResult:
    status:str; reason:str|None=None; provider:str|None=None; model:str|None=None; invocation_type:str|None=None; prompt_digest:str|None=None; output:str|None=None; response_id:str|None=None

def supported_providers(): return tuple(sorted((*OPENAI_COMPATIBLE,*SPECIALIZED,*LOCAL)))
def _digest(value): return hashlib.sha256(value.encode("utf-8")).hexdigest()

class LLMGateway:
    def __init__(self,env=None): self.env=os.environ if env is None else env
    def provider_config(self):
        provider=self.env.get("OLA_LLM_PROVIDER","openai").strip().lower()
        defaults={"openai":"gpt-5.6-luna","openrouter":"openai/gpt-5.6-luna","mistral":"mistral-small-latest","groq":"llama-3.3-70b-versatile","together":"meta-llama/Llama-3.3-70B-Instruct-Turbo","deepseek":"deepseek-chat","xai":"grok-4-fast-reasoning","anthropic":"claude-sonnet-4-5","gemini":"gemini-2.5-flash","ollama":"qwen2.5:0.5b-instruct"}
        model=self.env.get("OLA_LLM_MODEL") or self.env.get("NINA_CHAT_MODEL") or defaults.get(provider,"")
        if provider in OPENAI_COMPATIBLE:
            key,base=OPENAI_COMPATIBLE[provider]; return ProviderConfig(provider,model,self._base_url(base),key)
        if provider=="ollama": return ProviderConfig(provider,model,self.env.get("OLLAMA_BASE_URL","http://127.0.0.1:11434").rstrip("/"),None)
        if provider=="anthropic": return ProviderConfig(provider,model,self.env.get("ANTHROPIC_BASE_URL","https://api.anthropic.com").rstrip("/"),"ANTHROPIC_API_KEY")
        if provider=="gemini": return ProviderConfig(provider,model,self.env.get("GEMINI_BASE_URL","https://generativelanguage.googleapis.com").rstrip("/"),"GEMINI_API_KEY")
        return ProviderConfig(provider,model,"",None)
    def _base_url(self,default):
        requested=self.env.get("OLA_LLM_BASE_URL")
        if not requested: return default
        if self.env.get("OLA_LLM_ALLOW_CUSTOM_BASE_URL","").lower()!="true": return default
        parsed=urlparse(requested); allowed={x.strip().lower() for x in self.env.get("OLA_LLM_ALLOWED_BASE_HOSTS","").split(",") if x.strip()}
        if parsed.scheme not in {"https","http"} or not parsed.netloc or parsed.username or parsed.password or (parsed.hostname or "").lower() not in allowed: raise ValueError("custom LLM base URL host is not allowlisted")
        return requested.rstrip("/")
    def _required(self): return self.env.get("OLA_LLM_MODE","deterministic").strip().lower()=="required"
    def invoke(self,agent,task,context):
        try: cfg=self.provider_config()
        except ValueError as exc: return LLMResult("BLOCK",str(exc))
        prompt=json.dumps({"agent":agent,"task":task,"context":context},sort_keys=True,separators=(",",":")); digest=_digest(prompt)
        if cfg.provider not in supported_providers(): return LLMResult("BLOCK" if self._required() else "SKIPPED",f"unsupported LLM provider: {cfg.provider}")
        if cfg.api_key_env and not self.env.get(cfg.api_key_env): return LLMResult("BLOCK" if self._required() else "SKIPPED",f"{cfg.api_key_env} API key is missing")
        system="You are one agent in OLA di-OS. Return concise JSON-compatible reasoning output. Do not claim tools or evidence you did not actually use."
        try:
            if cfg.provider in OPENAI_COMPATIBLE: data=self._openai(cfg,system,prompt)
            elif cfg.provider=="ollama": data=self._ollama(cfg,system,prompt)
            elif cfg.provider=="anthropic": data=self._anthropic(cfg,system,prompt)
            elif cfg.provider=="gemini": data=self._gemini(cfg,system,prompt)
            else: raise RuntimeError("unsupported provider")
        except (httpx.HTTPError,ValueError,KeyError,RuntimeError,json.JSONDecodeError,TimeoutError) as exc:
            return LLMResult("BLOCK" if self._required() else "SKIPPED",f"LLM invocation failed: {exc.__class__.__name__}",cfg.provider,cfg.model,"real_llm",digest)
        return LLMResult("RECEIVED",provider=cfg.provider,model=cfg.model,invocation_type="real_llm",prompt_digest=digest,output=data["output"],response_id=data.get("response_id"))
    def _post(self,url,**kwargs):
        response=httpx.post(url,timeout=float(self.env.get("OLA_LLM_TIMEOUT","60")),trust_env=False,**kwargs)
        if len(response.content)>MAX_RESPONSE_BYTES: raise ValueError("LLM response exceeds size limit")
        response.raise_for_status(); return response
    def _openai(self,cfg,system,prompt):
        headers={"Authorization":f"Bearer {self.env[cfg.api_key_env]}","Content-Type":"application/json"}
        if cfg.provider=="openai":
            body=self._post(cfg.base_url+"/responses",headers=headers,json={"model":cfg.model,"input":[{"role":"system","content":system},{"role":"user","content":prompt}]}).json()
            output=body.get("output_text") or "\n".join(p.get("text","") for i in body.get("output",[]) for p in i.get("content",[]) if p.get("type") in {"output_text","text"})
        else:
            body=self._post(cfg.base_url+"/chat/completions",headers=headers,json={"model":cfg.model,"messages":[{"role":"system","content":system},{"role":"user","content":prompt}],"temperature":0}).json()
            output=body.get("choices",[{}])[0].get("message",{}).get("content")
        if not output: raise ValueError("provider returned no output text")
        return {"output":output,"response_id":body.get("id")}
    def _ollama(self,cfg,system,prompt):
        body=self._post(cfg.base_url+"/api/chat",headers={"Content-Type":"application/json"},json={"model":cfg.model,"messages":[{"role":"system","content":system},{"role":"user","content":prompt}],"stream":False,"options":{"temperature":0}}).json()
        output=body.get("message",{}).get("content")
        if not output: raise ValueError("Ollama returned no message content")
        return {"output":output,"response_id":body.get("id") or "ollama:"+_digest(json.dumps(body,sort_keys=True))}
    def _anthropic(self,cfg,system,prompt):
        body=self._post(cfg.base_url+"/v1/messages",headers={"x-api-key":self.env[cfg.api_key_env],"anthropic-version":"2023-06-01","content-type":"application/json"},json={"model":cfg.model,"max_tokens":1024,"system":system,"messages":[{"role":"user","content":prompt}]}).json()
        output="\n".join(p.get("text","") for p in body.get("content",[]) if p.get("type")=="text")
        if not output: raise ValueError("Anthropic returned no text")
        return {"output":output,"response_id":body.get("id")}
    def _gemini(self,cfg,system,prompt):
        body=self._post(f"{cfg.base_url}/v1beta/models/{cfg.model}:generateContent",headers={"content-type":"application/json","x-goog-api-key":self.env[cfg.api_key_env]},json={"systemInstruction":{"parts":[{"text":system}]},"contents":[{"role":"user","parts":[{"text":prompt}]}]}).json()
        output="\n".join(p.get("text","") for p in body.get("candidates",[{}])[0].get("content",{}).get("parts",[]) if p.get("text"))
        if not output: raise ValueError("Gemini returned no text")
        return {"output":output,"response_id":body.get("responseId") or "gemini:"+_digest(json.dumps(body,sort_keys=True))}
