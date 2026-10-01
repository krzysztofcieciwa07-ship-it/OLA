import hashlib
from typing import Any
from .llm_gateway import LLMGateway
SYSTEM_PROMPT="""You are NINA, a precise execution assistant.
Be useful, concise, and honest. Never claim an action was executed unless the execution endpoint returned VERIFIED evidence.
When a user asks for an action that requires execution, explain that the verified execution path is /nina-run.
"""
def chat(tenant_id:str,messages:list[dict[str,str]])->dict[str,Any]:
    if not messages:return {"status":"BLOCK","reason":"messages are required"}
    result=LLMGateway().invoke("nina_chat",SYSTEM_PROMPT,{"messages":messages[-20:]})
    if result.status!="RECEIVED":return {"status":"BLOCK","reason":result.reason or "LLM provider is not configured","message":"NINA conversational LLM access is not configured."}
    from .main import append_record
    append_record(tenant_id,"chat.received",{"provider":result.provider,"model":result.model,"invocation_type":result.invocation_type,"response_id":result.response_id,"response_digest":hashlib.sha256((result.output or "").encode()).hexdigest(),"message_count":len(messages)})
    return {"status":"RECEIVED","message":result.output,"provider":result.provider,"model":result.model,"invocation_type":result.invocation_type,"response_id":result.response_id}
