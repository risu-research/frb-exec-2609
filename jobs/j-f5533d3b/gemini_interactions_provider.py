from __future__ import annotations

import copy
import hashlib
import json
import os
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

try:
    from a0_3_protocol import ModelTurn, ToolCall, ProviderError, TOOL_ALLOWLIST, canonical_json, sha256_text
except ImportError:
    from protocol_projection import ModelTurn, ToolCall, ProviderError, TOOL_ALLOWLIST, canonical_json, sha256_text

GEMINI_INTERACTIONS_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"
GEMINI_MODEL_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}"
LOCKED_MODEL = "gemini-3.8-flash"

TOOL_SCHEMAS = (
    {"type":"function","name":"list_files","description":"List editable files in the task workspace.","parameters":{"type":"object","properties":{},"required":[],"additionalProperties":False}},
    {"type":"function","name":"read_file","description":"Read one UTF-8 file from the editable task workspace.","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"],"additionalProperties":False}},
    {"type":"function","name":"write_file","description":"Replace or create one UTF-8 file inside the editable task workspace.","parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"}},"required":["path","content"],"additionalProperties":False}},
    {"type":"function","name":"run_verifier","description":"Submit the current repository state to its verifier and return the verifier status.","parameters":{"type":"object","properties":{},"required":[],"additionalProperties":False}},
)
if tuple(t["name"] for t in TOOL_SCHEMAS) != TOOL_ALLOWLIST: raise RuntimeError("tool schema / protocol allowlist mismatch")

@dataclass(frozen=True)
class RawTransportResponse:
    raw_text: str
    value: dict[str, Any]
Transport = Callable[[dict[str, Any]], RawTransportResponse]
MetadataTransport = Callable[[str], RawTransportResponse]

def _canonical_sha256_text(text: str) -> str: return hashlib.sha256(text.encode("utf-8")).hexdigest()

def _default_transport(api_key: str, timeout_seconds: float) -> Transport:
    def call(payload: dict[str, Any]) -> RawTransportResponse:
        data = canonical_json(payload).encode("utf-8")
        req = urllib.request.Request(GEMINI_INTERACTIONS_ENDPOINT,data=data,method="POST",headers={"x-goog-api-key":api_key,"Content-Type":"application/json","User-Agent":"neutral-adapter-v1/1"})
        try:
            with urllib.request.urlopen(req, timeout=timeout_seconds) as response: raw=response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            retryable = exc.code == 429 or 500 <= exc.code <= 599
            raise ProviderError(f"Gemini HTTP {exc.code}", output_observed=False, retryable=retryable) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            raise ProviderError("Gemini transport failure", output_observed=False, retryable=True) from exc
        try: parsed=json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProviderError("Gemini response was not valid JSON",output_observed=False,retryable=False,raw_response_sha256=_canonical_sha256_text(raw)) from exc
        if not isinstance(parsed,dict): raise ProviderError("Gemini response was not an object",output_observed=False,retryable=False,raw_response_sha256=_canonical_sha256_text(raw))
        return RawTransportResponse(raw,parsed)
    return call

def _default_metadata_transport(api_key: str, timeout_seconds: float) -> MetadataTransport:
    def call(model: str) -> RawTransportResponse:
        req=urllib.request.Request(GEMINI_MODEL_ENDPOINT.format(model=model),method="GET",headers={"x-goog-api-key":api_key,"User-Agent":"neutral-adapter-v1/1"})
        try:
            with urllib.request.urlopen(req,timeout=timeout_seconds) as response: raw=response.read().decode("utf-8")
        except urllib.error.HTTPError as exc: raise ProviderError(f"Gemini model metadata HTTP {exc.code}",output_observed=False,retryable=False) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc: raise ProviderError("Gemini metadata transport failure",output_observed=False,retryable=True) from exc
        try: parsed=json.loads(raw)
        except json.JSONDecodeError as exc: raise ProviderError("Gemini model metadata was not valid JSON",output_observed=False,retryable=False,raw_response_sha256=_canonical_sha256_text(raw)) from exc
        if not isinstance(parsed,dict): raise ProviderError("Gemini model metadata was not an object",output_observed=False,retryable=False)
        return RawTransportResponse(raw,parsed)
    return call

def validate_metadata_response(response: RawTransportResponse, model: str = LOCKED_MODEL) -> dict[str, Any]:
    if model != LOCKED_MODEL: raise ValueError("only locked stable model permitted")
    name=response.value.get("name")
    if name not in {model,f"models/{model}"}: raise ProviderError("metadata model identity mismatch",output_observed=False,retryable=False,raw_response_sha256=_canonical_sha256_text(response.raw_text))
    return {"model":model,"raw_response_sha256":_canonical_sha256_text(response.raw_text),"metadata_name":name}

def probe_model_visibility(*, api_key: str|None=None, transport: MetadataTransport|None=None, timeout_seconds: float=30.0) -> dict[str,Any]:
    if transport is None:
        key=api_key or os.environ.get("GEMINI_API_KEY")
        if not key: raise RuntimeError("GEMINI_API_KEY is required for metadata probe")
        transport=_default_metadata_transport(key,timeout_seconds)
    return validate_metadata_response(transport(LOCKED_MODEL),LOCKED_MODEL)

def _usage(response: dict[str,Any]) -> tuple[int,int,dict[str,int]]:
    usage=response.get("usage")
    if not isinstance(usage,dict): raise ValueError("usage missing")
    def strict(name: str, required: bool=True) -> int:
        if name not in usage:
            if required: raise ValueError(f"usage {name} missing")
            return 0
        v=usage[name]
        if type(v) is not int or v<0: raise ValueError(f"usage {name} invalid")
        return v
    inp=strict("total_input_tokens"); vis=strict("total_output_tokens"); thought=strict("total_thought_tokens",False); out=vis+thought
    return inp,out,{"visible_output_tokens":vis,"thought_tokens":thought,"controller_output_tokens":out}

def _text_content(content: Any) -> list[str]:
    if not isinstance(content,list): raise ValueError("model_output content malformed")
    out=[]
    for part in content:
        if not isinstance(part,dict) or part.get("type")!="text" or not isinstance(part.get("text"),str): raise ValueError("non-text model output is outside frozen surface")
        out.append(part["text"])
    return out

class GeminiInteractionsProvider:
    def __init__(self,*,model: str=LOCKED_MODEL,thinking_level: str="high",max_output_tokens_per_turn: int=12000,api_key: str|None=None,transport: Transport|None=None,timeout_seconds: float=120.0):
        if model!=LOCKED_MODEL: raise ValueError("wrong model")
        if thinking_level!="high": raise ValueError("wrong thinking level")
        if max_output_tokens_per_turn!=12000: raise ValueError("wrong per-turn cap")
        self.model=model; self.thinking_level=thinking_level; self.max_output_tokens_per_turn=max_output_tokens_per_turn
        if transport is None:
            key=api_key or os.environ.get("GEMINI_API_KEY")
            if not key: raise RuntimeError("GEMINI_API_KEY is required for live provider")
            transport=_default_transport(key,timeout_seconds)
        self._transport=transport; self._system_instruction=None; self._history_steps=[]; self._seen_tool_results=set(); self._known_calls={}
        self.raw_responses=[]; self.request_digests=[]; self.usage_details=[]
    def _ingest_messages(self,messages):
        if self._system_instruction is None:
            if len(messages)<2 or messages[0].get("role")!="system" or messages[1].get("role")!="user": raise ProviderError("protocol messages missing system/user prefix",output_observed=False,retryable=False)
            system=messages[0].get("content"); user=messages[1].get("content")
            if not isinstance(system,str) or not system or not isinstance(user,str) or not user: raise ProviderError("protocol system/user content malformed",output_observed=False,retryable=False)
            self._system_instruction=system; self._history_steps.append({"type":"user_input","content":[{"type":"text","text":user}]})
        elif messages[0].get("content")!=self._system_instruction: raise ProviderError("system instruction changed",output_observed=False,retryable=False)
        for message in messages:
            if message.get("role")!="tool": continue
            call_id=message.get("tool_call_id"); name=message.get("name")
            if not isinstance(call_id,str) or not call_id: raise ProviderError("tool result missing call id",output_observed=False,retryable=False)
            if call_id in self._seen_tool_results: continue
            if call_id not in self._known_calls: raise ProviderError("tool result references unknown call",output_observed=False,retryable=False)
            expected=self._known_calls[call_id]
            if name!=expected: raise ProviderError("tool result name/call mismatch",output_observed=False,retryable=False)
            content=message.get("content")
            if not isinstance(content,str): raise ProviderError("tool result content malformed",output_observed=False,retryable=False)
            self._history_steps.append({"type":"function_result","name":expected,"call_id":call_id,"is_error":content.startswith("TOOL_ERROR:"),"result":[{"type":"text","text":content}]}); self._seen_tool_results.add(call_id)
    def _payload(self):
        return {"model":self.model,"input":copy.deepcopy(self._history_steps),"system_instruction":self._system_instruction,"tools":copy.deepcopy(list(TOOL_SCHEMAS)),"store":False,"background":False,"stream":False,"generation_config":{"thinking_level":self.thinking_level,"thinking_summaries":"none","max_output_tokens":self.max_output_tokens_per_turn,"tool_choice":"auto"}}
    def generate(self,messages,tool_names):
        if tuple(tool_names)!=TOOL_ALLOWLIST: raise ProviderError("tool allowlist mismatch",output_observed=False,retryable=False)
        self._ingest_messages(messages); payload=self._payload(); self.request_digests.append(sha256_text(canonical_json(payload)))
        tr=self._transport(payload)
        if not isinstance(tr,RawTransportResponse) or not isinstance(tr.value,dict): raise ProviderError("transport contract violation",output_observed=False,retryable=False)
        raw=tr.raw_text; response=tr.value; raw_digest=_canonical_sha256_text(raw); self.raw_responses.append(raw)
        steps=response.get("steps"); observed=isinstance(steps,list) and bool(steps); rid=response.get("id") if isinstance(response.get("id"),str) and response.get("id") else None; returned_model=response.get("model") if isinstance(response.get("model"),str) and response.get("model") else None
        try: input_tokens,output_tokens,detail=_usage(response)
        except ValueError as exc: raise ProviderError(str(exc),output_observed=observed,retryable=False,raw_response_sha256=raw_digest,response_id=rid,model_id=returned_model) from exc
        self.usage_details.append(detail)
        def err(msg,obs=None): return ProviderError(msg,output_observed=observed if obs is None else obs,retryable=False,raw_response_sha256=raw_digest,response_id=rid,model_id=returned_model,input_tokens=input_tokens,output_tokens=output_tokens)
        if response.get("errors"): raise err("provider response contained errors")
        if rid is None or returned_model is None: raise err("response identity missing",observed)
        if returned_model!=self.model: raise err("returned model identity mismatch")
        if not isinstance(steps,list): raise err("provider steps missing",False)
        calls=[]; texts=[]; ids=set()
        for step in steps:
            if not isinstance(step,dict): raise err("malformed interaction step",True)
            typ=step.get("type")
            if typ=="thought":
                sig=step.get("signature")
                if not isinstance(sig,str) or not sig: raise err("thought signature missing",True)
                if step.get("summary") not in (None,[]): raise err("unexpected thought summary under summaries=none",True)
            elif typ=="function_call":
                name=step.get("name"); cid=step.get("id"); args=step.get("arguments")
                if name not in TOOL_ALLOWLIST or not isinstance(cid,str) or not cid or not isinstance(args,dict): raise err("invalid function call",True)
                if cid in ids or cid in self._known_calls: raise err("duplicate function call id",True)
                ids.add(cid); calls.append(ToolCall(cid,name,copy.deepcopy(args)))
            elif typ=="model_output":
                try: texts.extend(_text_content(step.get("content")))
                except ValueError as exc: raise err(str(exc),True) from exc
            else: raise err(f"unsupported interaction step type: {typ}",True)
        status=response.get("status")
        if calls:
            if status!="requires_action": raise err("function-call response did not require action",True)
        elif status!="completed": raise err(f"nonterminal interaction status without function call: {status}",observed)
        self._history_steps.extend(copy.deepcopy(steps))
        for c in calls: self._known_calls[c.call_id]=c.name
        return ModelTurn(response_id=rid,model_id=returned_model,text="\n".join(texts),tool_calls=tuple(calls),input_tokens=input_tokens,output_tokens=output_tokens,raw_response_sha256=raw_digest)
