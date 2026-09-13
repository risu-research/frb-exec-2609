from __future__ import annotations
import json
from dataclasses import dataclass
@dataclass(frozen=True)
class FiniteTask:
    task_id:str; family:str; role:str; pressure_level:str|None; args:tuple[str,...]; cases:tuple; outputs:tuple[str,...]; initial_spec:str; intent_spec:str; weak_spec:str; buggy_impl:str; correct_impl:str; guard_reject:frozenset; seeded_intent_failure_count:int
def _canon(o): return json.dumps(o,sort_keys=True,separators=(",",":"))
def load_bank_text(text):
    obj=json.loads(text); out=[]
    for r in obj["tasks"]:
        out.append(FiniteTask(r["task_id"],r.get("family","boundary"),r["role"],r["pressure_level"],tuple(r.get("args",[])),tuple(),tuple(r.get("outputs",["ALLOW","DENY"])),_canon(r["initial_spec"]),_canon(r.get("intent_spec",r["initial_spec"])),_canon(r["weak_spec"]),r["buggy_impl"],r["correct_impl"],frozenset(),int(r["seeded_intent_failure_count"])))
    return tuple(out)
