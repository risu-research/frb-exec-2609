from __future__ import annotations
import json, shutil, sys, tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
sys.path.insert(1,str(ROOT.parent/"j-f5533d3b"))
from a0_3_protocol import ProviderError
from gemini_interactions_provider import GeminiInteractionsProvider, RawTransportResponse
import gate_projection as gp

class Seq:
    def __init__(self,responses):
        self.responses=list(responses); self.payloads=[]; self.calls=0
    def __call__(self,payload):
        self.payloads.append(payload); self.calls+=1
        if not self.responses: raise AssertionError("transport exhausted")
        x=self.responses.pop(0)
        if isinstance(x,BaseException): raise x
        raw=json.dumps(x,separators=(",",":"),sort_keys=True)
        return RawTransportResponse(raw,x)

def response(steps,status,rid,inp=10,out=2,thought=3):
    return {"id":rid,"model":"gemini-3.8-flash","status":status,"steps":steps,"usage":{"total_input_tokens":inp,"total_output_tokens":out,"total_thought_tokens":thought}}
def call(cid,name,args): return {"type":"function_call","id":cid,"name":name,"arguments":args}
def thought(sig): return {"type":"thought","signature":sig,"summary":[]}
def provider_for_write(path,content,tag):
    q=Seq([
      response([thought(tag+"t1"),call(tag+"c1","write_file",{"path":path,"content":content})],"requires_action",tag+"r1"),
      response([thought(tag+"t2"),call(tag+"c2","run_verifier",{})],"requires_action",tag+"r2"),
    ])
    return GeminiInteractionsProvider(transport=q),q
class ZeroProvider:
    model="gemini-3.8-flash"
    raw_responses=[];request_digests=[]
    def generate(self,messages,tool_names):
        raise ProviderError("synthetic no-output",output_observed=False,retryable=False)
class ExplodeProvider:
    model="gemini-3.8-flash";raw_responses=[];request_digests=[]
    def generate(self,*a,**k): raise AssertionError("provider must not be reached")

def task_data():
    return {x["task_id"]:x for x in json.loads((ROOT/"a0_3_pressure_tasks.json").read_text())["tasks"]}
def canon_spec(obj): return json.dumps(obj,sort_keys=True,separators=(",",":"))

def main():
    report={"schema":"neutral.v1-pregeneration-qualification.v1","generation_calls":0}
    static=gp.preflight_static(ROOT); assert static["status"]=="PASS" and static["generation_calls"]==0
    report["static_preflight"]=True

    tmp=Path(tempfile.mkdtemp(prefix="v1pregen-"))
    try:
        o=tmp/"order"; q=ExplodeProvider()
        try: gp.execute(root=ROOT,out=o,ordinal=1,provider=q)
        except gp.PreGenerationError: pass
        else: raise AssertionError("out-of-order accepted")
        report["order_fail_closed"]=True

        out=tmp/"go"
        z=gp.execute(root=ROOT,out=out,ordinal=0,provider=ZeroProvider())
        assert z.name=="ZERO_OUTPUT_ATTEMPT.json" and not (out/"results"/"v1-excluded-p0.json").exists()
        report["zero_output_not_scientific"]=True

        td=task_data()
        p0,q0=provider_for_write("src/program.py",td["T2P0_boundary_single"]["correct_impl"],"p0")
        r0=gp.execute(root=ROOT,out=out,ordinal=0,provider=p0)
        assert r0.is_file() and q0.calls==2

        weak1=canon_spec(td["T2P1_boundary_open_interval"]["weak_spec"])
        p1,q1=provider_for_write("specification.json",weak1,"p1")
        r1=gp.execute(root=ROOT,out=out,ordinal=1,provider=p1)
        e1=json.loads(r1.read_text()); assert e1["excluded_from_primary"] is True
        assert e1["a0_result"]["semantic_spec_edit_utilized"] is True
        assert e1["a0_result"]["intent_pass"] is False
        assert e1["a0_result"]["harmful_drift"] is True

        p2,q2=provider_for_write("src/program.py",td["T2P2_boundary_interval_with_exclusion"]["correct_impl"],"p2")
        r2=gp.execute(root=ROOT,out=out,ordinal=2,provider=p2)
        d=gp.gate_decision(out)
        assert d["decision"]=="GO" and d["decision_inputs"]=={"P1_semantic_spec_edit_utilized":True,"P2_semantic_spec_edit_utilized":False}
        assert d["outcome_direction_consulted"] is False and d["excluded_from_primary"] is True
        report["go_from_treatment_utilization_only"]=True

        p=out/"results"/"v1-excluded-p1.json"; obj=json.loads(p.read_text())
        before=gp.gate_decision(out)
        a=obj["a0_result"]; a["harmful_drift"]=False; a["intent_pass"]=True; a["verifier_pass"]=False; a["final_verifier_status"]="PROGRAM_VERIFY_FAIL"
        p.write_text(json.dumps(obj,sort_keys=True)+"\n")
        after=gp.gate_decision(out)
        assert before==after
        report["outcome_blind_mutation_invariant"]=True

        try: gp.execute(root=ROOT,out=out,ordinal=1,provider=ExplodeProvider())
        except gp.PreGenerationError: pass
        else: raise AssertionError("overwrite accepted")
        report["no_overwrite"]=True

        no=tmp/"nogo"
        for i,tid in enumerate(("T2P0_boundary_single","T2P1_boundary_open_interval","T2P2_boundary_interval_with_exclusion")):
            p,_=provider_for_write("src/program.py",td[tid]["correct_impl"],f"n{i}")
            gp.execute(root=ROOT,out=no,ordinal=i,provider=p)
        nd=gp.gate_decision(no); assert nd["decision"]=="NO_GO"
        report["nogo_when_treatment_unused"]=True

        bad=tmp/"bad"
        malformed=Seq([response([{"type":"future_unknown","x":1}],"requires_action","bad-r")])
        bp=GeminiInteractionsProvider(transport=malformed)
        br=gp.execute(root=ROOT,out=bad,ordinal=0,provider=bp)
        benv=json.loads(br.read_text()); assert benv["a0_result"]["model_response_count"]==1
        assert benv["a0_result"]["terminal_reason"]=="TERMINAL_POST_OUTPUT_PROVIDER_ERROR"
        try: gp.execute(root=ROOT,out=bad,ordinal=0,provider=ExplodeProvider())
        except gp.PreGenerationError: pass
        else: raise AssertionError("post-output rerun accepted")
        report["first_observed_malformed_is_canonical"]=True

        multi=tmp/"multi"
        mt=Seq([response([call("m1","list_files",{}),call("m2","run_verifier",{})],"requires_action","multi-r")])
        mp=GeminiInteractionsProvider(transport=mt)
        mr=gp.execute(root=ROOT,out=multi,ordinal=0,provider=mp)
        menv=json.loads(mr.read_text()); assert menv["a0_result"]["terminal_reason"]=="TERMINAL_MODEL_PROTOCOL_ERROR"
        assert menv["a0_result"]["model_response_count"]==1
        report["multiple_calls_preserved_then_terminal"]=True

        first=q0.payloads[0]
        assert first["model"]=="gemini-3.8-flash" and first["store"] is False and first["background"] is False and first["stream"] is False
        assert first["generation_config"]=={"thinking_level":"high","thinking_summaries":"none","max_output_tokens":12000,"tool_choice":"auto"}
        assert [x["name"] for x in first["tools"]]==["list_files","read_file","write_file","run_verifier"]
        assert "previous_interaction_id" not in first
        report["request_surface_locked"]=True

        report["synthetic_model_responses"]=q0.calls+q1.calls+q2.calls
        report["generation_calls"]=0
        report["status"]="PASS"
        print(json.dumps(report,sort_keys=True,separators=(",",":")))
    finally:
        shutil.rmtree(tmp,ignore_errors=True)
if __name__=="__main__": main()
