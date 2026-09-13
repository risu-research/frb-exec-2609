from __future__ import annotations
import hashlib, json, time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TOOL_ALLOWLIST=("list_files","read_file","write_file","run_verifier")
def canonical_json(v): return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def sha256_text(s): return hashlib.sha256(s.encode()).hexdigest()

class ProviderError(RuntimeError):
    def __init__(self,message,*,output_observed,retryable=False,raw_response_sha256="",response_id=None,model_id=None,input_tokens=0,output_tokens=0):
        super().__init__(message); self.output_observed=output_observed; self.retryable=retryable; self.raw_response_sha256=raw_response_sha256; self.response_id=response_id; self.model_id=model_id; self.input_tokens=input_tokens; self.output_tokens=output_tokens

@dataclass(frozen=True)
class ToolCall:
    call_id:str; name:str; arguments:dict[str,Any]
@dataclass(frozen=True)
class ModelTurn:
    response_id:str; model_id:str; text:str; tool_calls:tuple[ToolCall,...]; input_tokens:int; output_tokens:int; raw_response_sha256:str=""
@dataclass(frozen=True)
class RunLimits:
    max_model_turns:int=16; max_tool_calls:int=48; max_verifier_calls:int=12; max_input_tokens:int=250000; max_output_tokens:int=60000; max_wall_seconds:float=600.0; max_pre_output_transport_retries:int=2
@dataclass(frozen=True)
class RunResult:
    stop_reason:str; verifier_status:str|None; model_id:str|None; transcript_root:str; counters:dict[str,Any]; final_text:str

class HashChainLedger:
    def __init__(self): self.events=[]; self.root="0"*64
    def append(self,kind,payload):
        core={"seq":len(self.events),"kind":kind,"payload":payload,"prev_hash":self.root}
        d=hashlib.sha256((self.root+"\n"+canonical_json(core)).encode()).hexdigest()
        e={**core,"hash":d}; self.events.append(e); self.root=d; return e
    def to_jsonl(self): return "".join(canonical_json(e)+"\n" for e in self.events)
    @staticmethod
    def verify_jsonl(text):
        prev="0"*64
        for i,line in enumerate(text.splitlines()):
            e=json.loads(line); core={k:e[k] for k in ("seq","kind","payload","prev_hash")}
            if e["seq"]!=i or e["prev_hash"]!=prev: raise RuntimeError("chain")
            d=hashlib.sha256((prev+"\n"+canonical_json(core)).encode()).hexdigest()
            if d!=e["hash"]: raise RuntimeError("hash")
            prev=d
        return prev

class WorkspaceTools:
    def __init__(self,root,verifier): self.root=Path(root); self.verifier=verifier
    def execute(self,name,args):
        if name=="list_files": return type("R",(),{"content":canonical_json(sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file())),"verifier_status":None})()
        if name=="read_file": return type("R",(),{"content":(self.root/args["path"]).read_text(),"verifier_status":None})()
        if name=="write_file":
            p=self.root/args["path"]; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(args["content"]); return type("R",(),{"content":"WRITE_OK","verifier_status":None})()
        if name=="run_verifier":
            s=self.verifier(); return type("R",(),{"content":s,"verifier_status":s})()
        raise RuntimeError("tool")

def run_agent_loop(*,provider,tools,core_instruction,task_prompt,limits=RunLimits(),clock=time.monotonic):
    ledger=HashChainLedger(); c={"model_turns":0,"tool_calls":0,"verifier_calls":0,"input_tokens":0,"output_tokens":0,"pre_output_retries":0}
    messages=[{"role":"system","content":core_instruction},{"role":"user","content":task_prompt}]
    status=None; model=None; final=""; stop="UNSET"; ledger.append("run_start",{})
    while True:
        try: turn=provider.generate(messages,TOOL_ALLOWLIST)
        except ProviderError as e:
            if e.output_observed:
                c["model_turns"]+=1; c["input_tokens"]+=e.input_tokens; c["output_tokens"]+=e.output_tokens; model=e.model_id or model; stop="TERMINAL_POST_OUTPUT_PROVIDER_ERROR"
            else: stop="TERMINAL_NONRETRYABLE_PROVIDER_ERROR"
            ledger.append("provider_error",{"output_observed":e.output_observed}); break
        c["model_turns"]+=1; c["input_tokens"]+=turn.input_tokens; c["output_tokens"]+=turn.output_tokens; model=turn.model_id; final=turn.text
        ledger.append("model_response",{"calls":len(turn.tool_calls),"raw":turn.raw_response_sha256})
        if len(turn.tool_calls)>1: stop="TERMINAL_MODEL_PROTOCOL_ERROR"; ledger.append("model_protocol_error",{"code":"MULTIPLE_TOOL_CALLS"}); break
        if not turn.tool_calls: stop="AGENT_STOP_NO_TOOL"; break
        tc=turn.tool_calls[0]; c["tool_calls"]+=1
        if tc.name=="run_verifier": c["verifier_calls"]+=1
        r=tools.execute(tc.name,tc.arguments); ledger.append("tool_result",{"name":tc.name,"status":r.verifier_status})
        messages.append({"role":"assistant","content":turn.text,"tool_call":{"id":tc.call_id,"name":tc.name,"arguments":tc.arguments}})
        messages.append({"role":"tool","tool_call_id":tc.call_id,"name":tc.name,"content":r.content})
        if r.verifier_status=="PASS": status="PASS"; stop="VERIFIER_PASS"; break
        if r.verifier_status is not None: status=r.verifier_status
    ledger.append("run_end",{"stop_reason":stop})
    return RunResult(stop,status,model,ledger.root,{**c,"elapsed_seconds":0.0},final),ledger
