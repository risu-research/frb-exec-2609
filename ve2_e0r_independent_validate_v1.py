from __future__ import annotations

"""Independent post-execution validator for VE2 E0R v1.

Does not import the E0R runtime microkernel, target-only builder, or ReplayMark.
Validates retained raw/canonical records, content fingerprints, cardinalities,
and the zero-science firewall from serialized artifacts only.
"""

import argparse
import hashlib
import json
from pathlib import Path


def cbytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def fp_record(value: dict[str, object]) -> bool:
    supplied = value.get("fingerprint")
    body = dict(value); body.pop("fingerprint", None)
    return supplied == hashlib.sha256(cbytes(body)).hexdigest()


def main() -> None:
    ap=argparse.ArgumentParser(); ap.add_argument("--runtime", required=True); ap.add_argument("--contracts", required=True); ap.add_argument("--out", required=True); a=ap.parse_args()
    runtime=json.loads(Path(a.runtime).read_text())
    root=Path(a.contracts)
    freeze=json.loads((root/"VE2_TARGET_ONLY_CONTRACT_FREEZE_RECEIPT_V1.json").read_text())
    independent=json.loads((root/"VE2_TARGET_ONLY_CONTRACT_INDEPENDENT_VALIDATION_V1.json").read_text())

    assert runtime["schema"]=="replaymark.ve2.e0r-runtime-qualification.v1"
    assert runtime["status"]=="PASS"
    assert runtime["home_assistant_version"]=="2026.9.0"
    assert runtime["qualified_families"]==["STATE","TIME","HOMEASSISTANT_START","SERVICE","CERTIFIED_NO_ACTION"]
    assert runtime["timeout_as_no_action"] is False
    assert runtime["transition_blueprint_executed"] is False
    assert runtime["scientific_fixture_executed"] is False
    assert runtime["historical_better_thermostat_action_dispatched"] is False
    assert runtime["scientific_result_opened"] is False
    assert runtime["frontier_result_seen"] is False
    assert runtime["ve2_home_assistant_scientific_cells"]==0
    assert runtime["ve2_replaymark_scientific_cells"]==0

    inv=runtime["native_invocations"]
    assert set(inv)=={"STATE","TIME","HOMEASSISTANT_START"}
    for family in ("STATE","TIME","HOMEASSISTANT_START"):
        w=inv[family]
        assert fp_record(w)
        assert w["family"]==family
        assert w["schema"]=="replaymark.ve2.native-invocation-witness.v1"
        assert isinstance(w["native"]["id"],str) and w["native"]["id"]
        assert isinstance(w["native"]["idx"],str) and w["native"]["idx"]
    assert inv["STATE"]["native"]["entity_id"]=="sensor.ve2_e0r_state_trigger"
    assert inv["STATE"]["native"]["from_state"]["state"]=="off"
    assert inv["STATE"]["native"]["to_state"]["state"]=="on"
    assert inv["STATE"]["action_context_id"] is not None
    assert "T" in inv["TIME"]["native"]["now_iso"]
    assert inv["HOMEASSISTANT_START"]["native"]["event"]=="start"

    hb=runtime["historical_behavior"]
    service=hb["service_behavior"]; noop=hb["no_action_behavior"]
    assert fp_record(service) and fp_record(noop)
    assert service["kind"]=="SERVICE" and service["native_service_event"] is not None
    assert noop["kind"]=="CERTIFIED_NO_ACTION" and noop["native_service_event"] is None
    assert noop["absence_certificate"]["qualified"] is True
    assert noop["absence_certificate"]["qualifying_service_count"]==0
    assert hb["service_boundary"]["parent"]["sequence"] < hb["service_boundary"]["event"]["sequence"]
    assert hb["service_boundary"]["parent"]["t_ns"] <= hb["service_boundary"]["event"]["t_ns"]
    assert hb["admit_service"]["historical_sink_calls"]==1
    assert hb["admit_no_action"]["historical_sink_calls"]==0
    assert hb["admit_no_action"]["certified_noop_reuse"] is True
    assert hb["block_service"]["historical_sink_calls"]==0
    assert hb["block_no_action"]["historical_sink_calls"]==0
    assert hb["duplicate_rejected"] is True
    assert hb["delegate_failure_consumed_before_retry"] is True
    assert len(hb["negative_cases"])==2 and all(x["rejected"] for x in hb["negative_cases"])

    assert freeze["schema"]=="replaymark.ve2.target-only-contract-freeze-receipt.v1"
    assert freeze["status"]=="PASS_PRE_SCIENCE"
    assert freeze["inputs"]["expected_frontier_files_read"] is False
    assert freeze["inputs"]["old_semantics_files_read"] is False
    assert freeze["inputs"]["new_direct_results_read"] is False
    assert freeze["contracts"]["T01"]["states"]==2
    assert freeze["contracts"]["T02"]["states"]==42
    assert independent["status"]=="PASS"
    assert independent["T01"]["new_target_law_exact"] is True
    assert independent["T02"]["new_target_law_exact"] is True
    assert independent["scientific_cells"]==0

    result={
      "schema":"replaymark.ve2.e0r-independent-validation.v1",
      "status":"PASS",
      "qualified_trigger_families":["STATE","TIME","HOMEASSISTANT_START"],
      "qualified_historical_behavior_kinds":["SERVICE","CERTIFIED_NO_ACTION"],
      "service_admit_sink_calls":1,
      "noop_admit_sink_calls":0,
      "block_sink_calls":0,
      "single_use_and_consume_before_delegate":"PASS",
      "target_only_contracts":{"T01":freeze["contracts"]["T01"]["contract_fingerprint"],"T02":freeze["contracts"]["T02"]["contract_fingerprint"]},
      "expected_frontier_material_used_by_contract_builder":False,
      "scientific_result_opened":False,
      "scientific_cells":0
    }
    Path(a.out).write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print(json.dumps(result,sort_keys=True))

if __name__=="__main__": main()
