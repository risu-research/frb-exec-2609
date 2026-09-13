from __future__ import annotations
import hashlib,json
from dataclasses import dataclass
from typing import Any
TOOL_ALLOWLIST=("list_files","read_file","write_file","run_verifier")
def canonical_json(value: Any)->str:return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)
def sha256_text(text: str)->str:return hashlib.sha256(text.encode("utf-8")).hexdigest()
class ProviderError(RuntimeError):
    def __init__(self,message: str,*,output_observed: bool,retryable: bool=False,raw_response_sha256: str="",response_id: str|None=None,model_id: str|None=None,input_tokens: int=0,output_tokens: int=0):
        super().__init__(message);self.output_observed=output_observed;self.retryable=retryable;self.raw_response_sha256=raw_response_sha256;self.response_id=response_id;self.model_id=model_id;self.input_tokens=input_tokens;self.output_tokens=output_tokens
@dataclass(frozen=True)
class ToolCall: call_id:str; name:str; arguments:dict[str,Any]
@dataclass(frozen=True)
class ModelTurn:
    response_id:str; model_id:str; text:str; tool_calls:tuple[ToolCall,...]; input_tokens:int; output_tokens:int; raw_response_sha256:str=""
def turn_protocol_error(turn: ModelTurn)->str|None:
    if not turn.response_id:return "MISSING_RESPONSE_ID"
    if not turn.model_id:return "MISSING_MODEL_ID"
    if type(turn.input_tokens) is not int or type(turn.output_tokens) is not int or turn.input_tokens<0 or turn.output_tokens<0:return "INVALID_USAGE"
    if len(turn.tool_calls)>1:return "MULTIPLE_TOOL_CALLS"
    for tc in turn.tool_calls:
        if not tc.call_id:return "INVALID_TOOL_CALL_ID"
        if tc.name not in TOOL_ALLOWLIST:return "NONALLOWLISTED_TOOL"
        if not isinstance(tc.arguments,dict):return "INVALID_TOOL_ARGUMENTS"
    return None
