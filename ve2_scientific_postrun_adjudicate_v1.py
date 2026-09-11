from __future__ import annotations

"""VE2 post-run adjudicator.

The first operation is verification of the immutable 16-stage raw seal. Only
thereafter are the frozen analysis model and expected-frontier files opened.
"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import ve2_transition_semantics_v1 as model

RAW_SEAL_SCHEMA = "replaymark.ve2.all-raw-stage-artifacts-sealed.v1"
STAGE_SCHEMA = "replaymark.ve2.scientific-native-stage.v1"
EXPECTED_STAGE_KEYS = [
    "T01_R0_OLD_HISTORY","T01_R1_OLD_HISTORY","T01_R0_NEW_DIRECT","T01_R1_NEW_DIRECT",
    "T01_R0_REPLAYMARK","T01_R1_REPLAYMARK","T01_R0_REPLAY_ALL","T01_R1_REPLAY_ALL",
    "T02_R0_OLD_HISTORY","T02_R1_OLD_HISTORY","T02_R0_NEW_DIRECT","T02_R1_NEW_DIRECT",
    "T02_R0_REPLAYMARK","T02_R1_REPLAYMARK","T02_R0_REPLAY_ALL","T02_R1_REPLAY_ALL",
]
T01_ROWS_DIGEST = "6d4b4ac7738885bcf1226161d84726926b15d3139502dd5e31499a4850328f2a"
T02_QUOTIENT_DIGEST = "c4c3d495df1659aaf94fb1d517b9fdd483759344c429e58aa51a45d415b74c25"
T02_ABSTRACT_DIGEST = "6292de3f4889bb69491faf40cdc3c421576ea750e4d70cb032a6b0bbc81c60ae"
T01_FRONTIER_SHA = "edad64a2b289f103712f9fe74877e713b8af5551"
T02_FRONTIER_SHA = "76d4ecabf6938e13b719d6350deb191106df5c57"


def cb(value: object) -> bytes:
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()


def sha(value: object) -> str:
    return hashlib.sha256(cb(value)).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def parse_key(key: str) -> tuple[str,int,str]:
    parts=key.split("_")
    require(len(parts)>=4, "stage-key")
    transition=parts[0]
    replica=int(parts[1][1:])
    stage="_".join(parts[2:]).lower()
    return transition,replica,stage


def verify_raw_seal(seal_path: Path, raw_dir: Path) -> tuple[dict[str,Any],dict[str,dict[str,Any]]]:
    seal=json.loads(seal_path.read_bytes())
    require(seal.get("schema")==RAW_SEAL_SCHEMA, "raw-seal-schema")
    require(seal.get("status")=="ALL_16_RAW_STAGES_SEALED", "raw-seal-status")
    require(seal.get("scientific_summary_emitted") is False, "raw-seal-summary")
    require(seal.get("expected_frontier_read_before_raw_seal") is False, "raw-seal-frontier-order")
    stages=seal.get("stages")
    require(isinstance(stages,list) and [x.get("stage_key") for x in stages]==EXPECTED_STAGE_KEYS, "raw-seal-order")
    docs:dict[str,dict[str,Any]]={}
    for item in stages:
        key=item["stage_key"]
        report=raw_dir/item["report_file"]
        validation=raw_dir/item["validation_file"]
        require(report.is_file() and validation.is_file(), "raw-seal-file-missing")
        require(file_sha(report)==item["report_file_sha256"], "raw-report-file-digest")
        require(file_sha(validation)==item["validation_file_sha256"], "raw-validation-file-digest")
        v=json.loads(validation.read_bytes())
        require(v.get("status")=="PASS", "raw-independent-validation")
        doc=json.loads(report.read_bytes())
        require(doc.get("schema")==STAGE_SCHEMA and doc.get("status")=="SEALED_RAW_STAGE", "raw-report-status")
        body=dict(doc); supplied=body.pop("result_sha256",None)
        require(supplied==sha(body)==item["stage_result_sha256"], "raw-stage-result-digest")
        docs[key]=doc
    body=dict(seal); supplied=body.pop("seal_sha256",None)
    require(supplied==sha(body), "raw-seal-digest")
    return seal,docs


def row_map(doc:dict[str,Any])->dict[str,dict[str,Any]]:
    rows=doc.get("rows")
    require(isinstance(rows,list),"rows")
    out={r["opaque_state_id"]:r for r in rows}
    require(len(out)==len(rows),"duplicate-row")
    return out


def action_equal(a:dict[str,Any],b:dict[str,Any])->bool:
    return cb(a)==cb(b)


def t01_adjudicate(docs:dict[str,dict[str,Any]], expected:dict[str,Any])->dict[str,Any]:
    rows=model.t01_rows()
    require(sha(rows)==T01_ROWS_DIGEST,"t01-model-digest")
    require(expected.get("schema")=="replaymark.ve2.t01.expected-frontier.v1","t01-frontier-schema")
    require(expected.get("rows")==rows,"t01-frontier-model-row-mismatch")
    per=[]
    for replica in (0,1):
        old=row_map(docs[f"T01_R{replica}_OLD_HISTORY"])
        new=row_map(docs[f"T01_R{replica}_NEW_DIRECT"])
        rm=row_map(docs[f"T01_R{replica}_REPLAYMARK"])
        ra=row_map(docs[f"T01_R{replica}_REPLAY_ALL"])
        old_agree=new_agree=blocked=unsafe=reused=0
        replay_all_attempts=0
        for exp in rows:
            sid=exp["execution_state_id"]
            old_agree += action_equal(old[sid]["native_projected_action"],exp["old_projected_action"])
            new_agree += action_equal(new[sid]["native_projected_action"],exp["new_projected_action"])
            admission=rm[sid]["presented_certificate"]["admission"]
            if admission=="BLOCK_REUSE": blocked+=1
            if admission=="ADMIT_REUSE": reused+=1
            if admission=="BLOCK_REUSE" and rm[sid]["dispatch"]["attempted"]:
                unsafe+=1
            if ra[sid]["dispatch"]["attempted"]:
                replay_all_attempts+=1
        metrics={
            "old_native_source_agreement":f"{old_agree}/2",
            "new_direct_source_agreement":f"{new_agree}/2",
            "direct_reference_disagreement":(2-old_agree)+(2-new_agree),
            "compatible_history_executed":reused,
            "retired_history_blocked_before_historical_sink":blocked,
            "unsafe_retired_historical_dispatch":unsafe,
            "replay_all_historical_dispatch_attempts":replay_all_attempts,
        }
        target=expected["promotion_per_replica"]
        require(metrics["old_native_source_agreement"]==target["old_native_source_agreement"],"t01-old-agreement")
        require(metrics["new_direct_source_agreement"]==target["new_direct_source_agreement"],"t01-new-agreement")
        require(metrics["direct_reference_disagreement"]==target["direct_reference_disagreement"],"t01-direct-disagreement")
        require(metrics["compatible_history_executed"]==target["compatible_history_executed"],"t01-compatible-executed")
        require(metrics["retired_history_blocked_before_historical_sink"]==target["retired_history_blocked_before_historical_sink"],"t01-retired-block")
        require(metrics["unsafe_retired_historical_dispatch"]==target["unsafe_retired_historical_dispatch"],"t01-unsafe")
        require(metrics["replay_all_historical_dispatch_attempts"]==expected["baselines"]["replay_all"]["historical_dispatch_attempts"],"t01-replay-all")
        per.append({"replica":replica,"metrics":metrics})
    total={
        "state_instances":4,
        "retired_history_blocked":sum(x["metrics"]["retired_history_blocked_before_historical_sink"] for x in per),
        "unsafe_retired_historical_dispatch":sum(x["metrics"]["unsafe_retired_historical_dispatch"] for x in per),
        "direct_reference_disagreement":sum(x["metrics"]["direct_reference_disagreement"] for x in per),
    }
    require(total==expected["two_replica_total"],"t01-two-replica-total")
    return {"status":"PASS","per_replica":per,"two_replica_total":total}


def t02_adjudicate(docs:dict[str,dict[str,Any]], expected:dict[str,Any])->dict[str,Any]:
    abstract,quotient=model.t02_quotient()
    require(sha(abstract)==T02_ABSTRACT_DIGEST,"t02-abstract-model-digest")
    require(sha(quotient)==T02_QUOTIENT_DIGEST,"t02-quotient-model-digest")
    require(expected.get("schema")=="replaymark.ve2.t02.expected-frontier.v1","t02-frontier-schema")
    qmeta=expected["causal_path_quotient_table"]
    require(qmeta["canonical_rows_sha256"]==T02_QUOTIENT_DIGEST and qmeta["row_count"]==42,"t02-frontier-quotient")
    require(sum(int(r["weight_in_144_state_superspace"]) for r in quotient)==144,"t02-weight-sum")
    compatible=[r for r in quotient if action_equal(r["old_projected_action"],r["new_projected_action"])]
    retired=[r for r in quotient if not action_equal(r["old_projected_action"],r["new_projected_action"])]
    require(len(compatible)==18 and len(retired)==24,"t02-model-population")
    require(sum(int(r["weight_in_144_state_superspace"]) for r in compatible)==97,"t02-compatible-weight")
    require(sum(int(r["weight_in_144_state_superspace"]) for r in retired)==47,"t02-retired-weight")
    per=[]
    for replica in (0,1):
        old=row_map(docs[f"T02_R{replica}_OLD_HISTORY"])
        new=row_map(docs[f"T02_R{replica}_NEW_DIRECT"])
        rm=row_map(docs[f"T02_R{replica}_REPLAYMARK"])
        ra=row_map(docs[f"T02_R{replica}_REPLAY_ALL"])
        old_agree=new_agree=reused=blocked=unsafe=unnecessary=0
        for exp in quotient:
            sid=exp["execution_state_id"]
            old_agree += action_equal(old[sid]["native_projected_action"],exp["old_projected_action"])
            new_agree += action_equal(new[sid]["native_projected_action"],exp["new_projected_action"])
            is_compatible=action_equal(exp["old_projected_action"],exp["new_projected_action"])
            admission=rm[sid]["presented_certificate"]["admission"]
            if is_compatible and admission=="ADMIT_REUSE": reused+=1
            if (not is_compatible) and admission=="BLOCK_REUSE": blocked+=1
            if (not is_compatible) and rm[sid]["dispatch"]["attempted"]: unsafe+=1
            if rm[sid].get("caller_native_recovery") is not False: unnecessary+=1
            behavior=old[sid]["historical_behavior"]
            require(ra[sid]["dispatch"]["attempted"]==(behavior["kind"]=="SERVICE"),"t02-replay-all-policy")
        metrics={
            "old_native_source_agreement":f"{old_agree}/42",
            "new_direct_source_agreement":f"{new_agree}/42",
            "direct_reference_disagreement":(42-old_agree)+(42-new_agree),
            "replaymark_compatible_classes_executed":reused,
            "replaymark_retired_classes_blocked":blocked,
            "unnecessary_native_recovery":unnecessary,
            "unsafe_retired_historical_dispatch":unsafe,
            "weighted_abstract_frontier":{"compatible":97,"retired":47},
        }
        require(metrics==expected["promotion_per_replica"],"t02-promotion-per-replica")
        per.append({"replica":replica,"metrics":metrics})
    total={
        "compatible_class_reuse":sum(x["metrics"]["replaymark_compatible_classes_executed"] for x in per),
        "direct_reference_disagreement":sum(x["metrics"]["direct_reference_disagreement"] for x in per),
        "quotient_state_instances":84,
        "retired_class_block":sum(x["metrics"]["replaymark_retired_classes_blocked"] for x in per),
        "unnecessary_native_recovery":sum(x["metrics"]["unnecessary_native_recovery"] for x in per),
        "unsafe_retired_historical_dispatch":sum(x["metrics"]["unsafe_retired_historical_dispatch"] for x in per),
        "weighted_abstract_state_instances":288,
        "weighted_compatible":194,
        "weighted_retired":94,
    }
    require(total==expected["two_replica_total"],"t02-two-replica-total")
    return {"status":"PASS","per_replica":per,"two_replica_total":total,"quotient_rows_sha256":sha(quotient)}


def main()->None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--raw-dir",required=True)
    ap.add_argument("--raw-seal",required=True)
    ap.add_argument("--t01-frontier",required=True)
    ap.add_argument("--t02-frontier",required=True)
    ap.add_argument("--out",required=True)
    args=ap.parse_args()
    raw_dir=Path(args.raw_dir)
    seal,docs=verify_raw_seal(Path(args.raw_seal),raw_dir)
    # The two answer-bearing files are opened only after the complete raw seal
    # has been independently verified above.
    t01_path=Path(args.t01_frontier); t02_path=Path(args.t02_frontier)
    require(file_sha(t01_path)==T01_FRONTIER_SHA,"t01-frontier-raw-sha")
    require(file_sha(t02_path)==T02_FRONTIER_SHA,"t02-frontier-raw-sha")
    t01_expected=json.loads(t01_path.read_bytes())
    t02_expected=json.loads(t02_path.read_bytes())
    t01=t01_adjudicate(docs,t01_expected)
    t02=t02_adjudicate(docs,t02_expected)
    result={
        "schema":"replaymark.ve2.independent-postrun-adjudication.v1",
        "status":"PASS" if t01["status"]=="PASS" and t02["status"]=="PASS" else "FAIL",
        "raw_seal_sha256":seal["seal_sha256"],
        "t01":t01,
        "t02":t02,
        "scientific_cells":176,
        "raw_stage_instances":176,
        "frontier_read_only_after_raw_seal":True,
        "result_dependent_rerun_authorized":False,
    }
    result["adjudication_sha256"]=sha(result)
    Path(args.out).write_text(json.dumps(result,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":result["status"],"scientific_cells":176,"adjudication_sha256":result["adjudication_sha256"]},sort_keys=True))
    if result["status"]!="PASS": raise SystemExit(2)


if __name__=="__main__":
    main()
