from __future__ import annotations
import hashlib,json,time
from dataclasses import dataclass
from pathlib import Path
from typing import Any,Callable,Protocol

TOOL_ALLOWLIST=("list_files","read_file","write_file","run_verifier")
TERMINAL_VERIFIER_STATUSES={"TARGET_INTEGRITY_REJECTED","TARGET_SEMANTIC_POLICY_REJECTED","SPEC_INVALID","PROGRAM_VERIFY_FAIL","PASS"}

def canonical_json(value:Any)->str:
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def sha256_text(text:str)->str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
class ProtocolError(RuntimeError): pass
class ToolFailure(RuntimeError):
    ALLOWED={"BAD_ARGUMENTS","PATH_DENIED","NOT_FOUND","NOT_UTF8","READ_LIMIT","WRITE_LIMIT","IO_ERROR"}
    def __init__(self,code:str):
        if code not in self.ALLOWED: raise ValueError(f"unknown tool failure code: {code}")
        super().__init__(code); self.code=code
class ProviderError(RuntimeError):
    def __init__(self,message:str,*,output_observed:bool,retryable:bool=False,raw_response_sha256:str="",response_id:str|None=None,model_id:str|None=None,input_tokens:int=0,output_tokens:int=0):
        super().__init__(message); self.output_observed=output_observed; self.retryable=retryable; self.raw_response_sha256=raw_response_sha256; self.response_id=response_id; self.model_id=model_id; self.input_tokens=max(0,int(input_tokens)) if isinstance(input_tokens,int) else 0; self.output_tokens=max(0,int(output_tokens)) if isinstance(output_tokens,int) else 0
@dataclass(frozen=True)
class RunLimits:
    max_model_turns:int=16; max_tool_calls:int=48; max_verifier_calls:int=12; max_input_tokens:int=250000; max_output_tokens:int=60000; max_wall_seconds:float=600.0; max_pre_output_transport_retries:int=2
@dataclass(frozen=True)
class ToolCall:
    call_id:str; name:str; arguments:dict[str,Any]
@dataclass(frozen=True)
class ModelTurn:
    response_id:str; model_id:str; text:str; tool_calls:tuple[ToolCall,...]; input_tokens:int; output_tokens:int; raw_response_sha256:str=""
class Provider(Protocol):
    def generate(self,messages:list[dict[str,Any]],tool_names:tuple[str,...])->ModelTurn:...
class HashChainLedger:
    def __init__(self): self.events=[]; self.root="0"*64
    def append(self,kind:str,payload:dict[str,Any]):
        if not kind or not isinstance(payload,dict): raise ProtocolError("bad ledger event")
        core={"seq":len(self.events),"kind":kind,"payload":payload,"prev_hash":self.root}; digest=hashlib.sha256((self.root+"\n"+canonical_json(core)).encode()).hexdigest(); event={**core,"hash":digest}; self.events.append(event); self.root=digest; return event
    def to_jsonl(self): return "".join(canonical_json(e)+"\n" for e in self.events)
    @staticmethod
    def verify_jsonl(text:str):
        prev="0"*64; seq=0
        for line in text.splitlines():
            e=json.loads(line)
            if set(e)!={"seq","kind","payload","prev_hash","hash"}: raise ProtocolError("bad event keys")
            if e["seq"]!=seq or e["prev_hash"]!=prev: raise ProtocolError("broken chain order")
            core={k:e[k] for k in ("seq","kind","payload","prev_hash")}; digest=hashlib.sha256((prev+"\n"+canonical_json(core)).encode()).hexdigest()
            if digest!=e["hash"]: raise ProtocolError("broken event hash")
            prev=digest; seq+=1
        return prev
@dataclass
class RunCounters:
    model_turns:int=0; tool_calls:int=0; verifier_calls:int=0; input_tokens:int=0; output_tokens:int=0; pre_output_retries:int=0
@dataclass(frozen=True)
class ToolResult:
    content:str; verifier_status:str|None=None; tool_error_code:str|None=None
@dataclass(frozen=True)
class RunResult:
    stop_reason:str; verifier_status:str|None; model_id:str|None; transcript_root:str; counters:dict[str,Any]; final_text:str

def retry_disposition(error:ProviderError,counters:RunCounters,limits:RunLimits)->str:
    if error.output_observed: return "TERMINAL_POST_OUTPUT_PROVIDER_ERROR"
    if not error.retryable: return "TERMINAL_NONRETRYABLE_PROVIDER_ERROR"
    if counters.pre_output_retries<limits.max_pre_output_transport_retries: return "RETRY_PRE_OUTPUT_TRANSPORT"
    return "TERMINAL_PRE_OUTPUT_RETRY_EXHAUSTED"

def _safe_relpath(root:Path,supplied:str)->Path:
    if not isinstance(supplied,str) or not supplied or "\x00" in supplied: raise ToolFailure("BAD_ARGUMENTS")
    rel=Path(supplied)
    if rel.is_absolute() or ".." in rel.parts: raise ToolFailure("PATH_DENIED")
    target=(root/rel).resolve(); root_r=root.resolve()
    try: target.relative_to(root_r)
    except ValueError as exc: raise ToolFailure("PATH_DENIED") from exc
    return target
class WorkspaceTools:
    def __init__(self,root:Path,verifier:Callable[[],str],*,max_read_bytes:int=64000,max_write_bytes:int=64000): self.root=root.resolve(); self.verifier=verifier; self.max_read_bytes=max_read_bytes; self.max_write_bytes=max_write_bytes
    def execute(self,name:str,arguments:dict[str,Any])->ToolResult:
        if name not in TOOL_ALLOWLIST: raise ProtocolError("tool not allowed")
        if not isinstance(arguments,dict): raise ToolFailure("BAD_ARGUMENTS")
        if name=="list_files":
            if arguments: raise ToolFailure("BAD_ARGUMENTS")
            files=sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file()); return ToolResult(canonical_json(files))
        if name=="read_file":
            if set(arguments)!={"path"}: raise ToolFailure("BAD_ARGUMENTS")
            p=_safe_relpath(self.root,arguments["path"])
            try: data=p.read_bytes()
            except FileNotFoundError as exc: raise ToolFailure("NOT_FOUND") from exc
            except OSError as exc: raise ToolFailure("IO_ERROR") from exc
            if len(data)>self.max_read_bytes: raise ToolFailure("READ_LIMIT")
            try: return ToolResult(data.decode("utf-8"))
            except UnicodeDecodeError as exc: raise ToolFailure("NOT_UTF8") from exc
        if name=="write_file":
            if set(arguments)!={"path","content"} or not isinstance(arguments["content"],str): raise ToolFailure("BAD_ARGUMENTS")
            raw=arguments["content"].encode("utf-8")
            if len(raw)>self.max_write_bytes: raise ToolFailure("WRITE_LIMIT")
            p=_safe_relpath(self.root,arguments["path"])
            try: p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(raw)
            except OSError as exc: raise ToolFailure("IO_ERROR") from exc
            return ToolResult("WRITE_OK")
        if name=="run_verifier":
            if arguments: raise ToolFailure("BAD_ARGUMENTS")
            status=self.verifier()
            if status not in TERMINAL_VERIFIER_STATUSES: raise ProtocolError("verifier returned unknown status")
            return ToolResult(status,verifier_status=status)
        raise AssertionError(name)
def _budget_reason(c:RunCounters,limits:RunLimits,elapsed:float)->str|None:
    if elapsed>=limits.max_wall_seconds:return "WALL_TIME_LIMIT"
    if c.model_turns>=limits.max_model_turns:return "MODEL_TURN_LIMIT"
    if c.tool_calls>=limits.max_tool_calls:return "TOOL_CALL_LIMIT"
    if c.verifier_calls>=limits.max_verifier_calls:return "VERIFIER_CALL_LIMIT"
    if c.input_tokens>=limits.max_input_tokens:return "INPUT_TOKEN_LIMIT"
    if c.output_tokens>=limits.max_output_tokens:return "OUTPUT_TOKEN_LIMIT"
    return None
def _turn_protocol_error(turn:ModelTurn)->str|None:
    if not isinstance(turn.response_id,str) or not turn.response_id:return "MISSING_RESPONSE_ID"
    if not isinstance(turn.model_id,str) or not turn.model_id:return "MISSING_MODEL_ID"
    if type(turn.input_tokens) is not int or type(turn.output_tokens) is not int or turn.input_tokens<0 or turn.output_tokens<0:return "INVALID_USAGE"
    if len(turn.tool_calls)>1:return "MULTIPLE_TOOL_CALLS"
    for tc in turn.tool_calls:
        if not isinstance(tc.call_id,str) or not tc.call_id:return "INVALID_TOOL_CALL_ID"
        if tc.name not in TOOL_ALLOWLIST:return "NONALLOWLISTED_TOOL"
        if not isinstance(tc.arguments,dict):return "INVALID_TOOL_ARGUMENTS"
    return None
def run_agent_loop(*,provider:Provider,tools:WorkspaceTools,core_instruction:str,task_prompt:str,limits:RunLimits=RunLimits(),clock:Callable[[],float]=time.monotonic):
    ledger=HashChainLedger(); counters=RunCounters(); started=clock(); messages=[{"role":"system","content":core_instruction},{"role":"user","content":task_prompt}]; final_status=None; final_model=None; final_text=""; stop_reason="UNSET"
    ledger.append("run_start",{"core_instruction_sha256":sha256_text(core_instruction),"task_prompt_sha256":sha256_text(task_prompt),"tool_allowlist":list(TOOL_ALLOWLIST),"limits":limits.__dict__})
    while True:
        reason=_budget_reason(counters,limits,clock()-started)
        if reason: stop_reason=reason; ledger.append("stop",{"reason":reason}); break
        ledger.append("model_request",{"messages_sha256":sha256_text(canonical_json(messages)),"message_count":len(messages),"tool_names":list(TOOL_ALLOWLIST)})
        try: turn=provider.generate(messages,TOOL_ALLOWLIST)
        except ProviderError as exc:
            if exc.output_observed:
                counters.model_turns+=1; counters.input_tokens+=exc.input_tokens; counters.output_tokens+=exc.output_tokens
                if exc.model_id: final_model=exc.model_id
            disposition=retry_disposition(exc,counters,limits); ledger.append("provider_error",{"disposition":disposition,"error_type":type(exc).__name__,"message_sha256":sha256_text(str(exc)),"output_observed":exc.output_observed,"retryable":exc.retryable,"raw_response_sha256":exc.raw_response_sha256,"response_id":exc.response_id,"model_id":exc.model_id,"usage":{"input_tokens":exc.input_tokens,"output_tokens":exc.output_tokens}})
            if disposition=="RETRY_PRE_OUTPUT_TRANSPORT": counters.pre_output_retries+=1; continue
            stop_reason=disposition; break
        counters.model_turns+=1
        if type(turn.input_tokens) is int and turn.input_tokens>=0:counters.input_tokens+=turn.input_tokens
        if type(turn.output_tokens) is int and turn.output_tokens>=0:counters.output_tokens+=turn.output_tokens
        if isinstance(turn.model_id,str) and turn.model_id:final_model=turn.model_id
        if isinstance(turn.text,str):final_text=turn.text
        ledger.append("model_response",{"response_id":turn.response_id,"model_id":turn.model_id,"text_sha256":sha256_text(turn.text) if isinstance(turn.text,str) else "","tool_calls":[{"call_id":tc.call_id,"name":tc.name,"arguments_sha256":sha256_text(canonical_json(tc.arguments)) if isinstance(tc.arguments,dict) else ""} for tc in turn.tool_calls],"usage":{"input_tokens":turn.input_tokens,"output_tokens":turn.output_tokens},"raw_response_sha256":turn.raw_response_sha256})
        protocol_error=_turn_protocol_error(turn)
        if protocol_error: stop_reason="TERMINAL_MODEL_PROTOCOL_ERROR"; ledger.append("model_protocol_error",{"code":protocol_error}); ledger.append("stop",{"reason":stop_reason,"code":protocol_error}); break
        if counters.input_tokens>limits.max_input_tokens or counters.output_tokens>limits.max_output_tokens: stop_reason="TOKEN_LIMIT_POST_RESPONSE"; ledger.append("stop",{"reason":stop_reason}); break
        if not turn.tool_calls: stop_reason="AGENT_STOP_NO_TOOL"; ledger.append("stop",{"reason":stop_reason,"text_sha256":sha256_text(turn.text)}); break
        tc=turn.tool_calls[0]
        if counters.tool_calls>=limits.max_tool_calls: stop_reason="TOOL_CALL_LIMIT"; ledger.append("stop",{"reason":stop_reason}); break
        if tc.name=="run_verifier" and counters.verifier_calls>=limits.max_verifier_calls: stop_reason="VERIFIER_CALL_LIMIT"; ledger.append("stop",{"reason":stop_reason}); break
        counters.tool_calls+=1
        if tc.name=="run_verifier":counters.verifier_calls+=1
        try: result=tools.execute(tc.name,tc.arguments)
        except ToolFailure as exc: result=ToolResult(f"TOOL_ERROR:{exc.code}",tool_error_code=exc.code)
        ledger.append("tool_result",{"call_id":tc.call_id,"name":tc.name,"result_sha256":sha256_text(result.content),"verifier_status":result.verifier_status,"tool_error_code":result.tool_error_code})
        messages.append({"role":"assistant","content":turn.text,"tool_call":{"id":tc.call_id,"name":tc.name,"arguments":tc.arguments}}); messages.append({"role":"tool","tool_call_id":tc.call_id,"name":tc.name,"content":result.content})
        if result.verifier_status=="PASS": final_status="PASS"; stop_reason="VERIFIER_PASS"; ledger.append("stop",{"reason":stop_reason,"verifier_status":"PASS"}); break
        if result.verifier_status is not None:final_status=result.verifier_status
    elapsed=max(0.0,clock()-started); ledger.append("run_end",{"stop_reason":stop_reason,"verifier_status":final_status,"model_id":final_model,"counters":{**counters.__dict__,"elapsed_seconds":round(elapsed,6)}})
    return RunResult(stop_reason,final_status,final_model,ledger.root,{**counters.__dict__,"elapsed_seconds":elapsed},final_text),ledger
