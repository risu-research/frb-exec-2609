from __future__ import annotations

"""Deterministically derive the HA-C1 archived fixture pack from the sealed N2 horizon capsule.

Selection is outcome-blind with respect to ReplayMark C1: every timestamped runtime
snapshot and every consequential Home Assistant climate service event in both frozen
replicas is retained. Service events are bound to the unique retained state event whose
context id equals the service event's context_parent_id. No expected C1 realizer output
is written into the fixture pack.
"""

import argparse
import json
from pathlib import Path

SCHEMA = "replaymark.ha-c1.archived-fixtures.v1"
OBS_SCHEMA = "replaymark.runtime.ha-bt-observation-record.v1"
ACT_SCHEMA = "replaymark.runtime.ha-bt-historical-action-record.v1"
CLOCK = "python.perf_counter_ns"
OBS_CAPTURE = "homeassistant.states.snapshot"
ACT_CAPTURE = "homeassistant.event_bus.EVENT_CALL_SERVICE"
ENTITIES = {
    "presence": "input_boolean.agentmark_presence",
    "motion": "binary_sensor.agentmark_motion",
    "night": "input_boolean.agentmark_night",
    "enable": "input_boolean.agentmark_enable",
    "climate": "climate.agentmark_thermostat",
}
SOURCE = {
    "repository": "risu-research/appeal-discovery-consumer",
    "workflow_run_id": 34010550012,
    "execution_head": "a4fcc99c18c28138218fb553cd4a95fa182cabec",
    "artifact_id": 9982336698,
    "artifact_zip_sha256": "7a594987991d407b0702411b70859d5d9eecb4034f43c8908f44e9cf6299a098",
    "home_assistant_image": "ghcr.io/home-assistant/home-assistant@sha256:372d991e58882a1d8c68c07e9aa3f3b509276e695355f73ccdb03baa70407293",
}


def replica_path(root: Path, replica: int) -> Path:
    return root / "RAW_REPLICAS" / f"replaymark-n2-horizon-runtime-r{replica}" / f"replica-{replica}.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("capsule_root", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    observations: list[dict[str, object]] = []
    actions: list[dict[str, object]] = []

    for replica in (0, 1):
        report = json.loads(replica_path(args.capsule_root, replica).read_text(encoding="utf-8"))
        if report.get("replica") != replica:
            raise AssertionError("replica identity mismatch")
        for section in ("depth1_rows", "depth2_rows"):
            rows = report[section]
            for row_index, row in enumerate(rows):
                # Retain every producer snapshot field with an actual monotonic timestamp.
                for field in sorted(row):
                    value = row[field]
                    if field.endswith("_snapshot") and isinstance(value, dict) and isinstance(value.get("t_ns"), int):
                        observations.append({
                            "source": {"replica": replica, "section": section, "row_index": row_index, "field": field},
                            "raw": {
                                "schema": OBS_SCHEMA,
                                "capture_point": OBS_CAPTURE,
                                "clock_domain": CLOCK,
                                "entities": dict(ENTITIES),
                                "snapshot": value,
                            },
                        })

                state_events = row["state_events"]
                by_context: dict[str, list[dict[str, object]]] = {}
                for event in state_events:
                    context_id = event.get("context_id")
                    if isinstance(context_id, str):
                        by_context.setdefault(context_id, []).append(event)

                # Retain every consequential service event; do not filter on preset outcome.
                for service_index, service in enumerate(row["service_events"]):
                    if (service.get("domain"), service.get("service")) != ("climate", "set_preset_mode"):
                        raise AssertionError("unexpected consequential service family in frozen N2 horizon artifact")
                    parent_id = service.get("context_parent_id")
                    parents = by_context.get(parent_id, [])
                    if len(parents) != 1:
                        raise AssertionError(("parent context cardinality", replica, section, row_index, service_index, parent_id, len(parents)))
                    parent = parents[0]
                    actions.append({
                        "source": {"replica": replica, "section": section, "row_index": row_index, "service_index": service_index},
                        "raw": {
                            "schema": ACT_SCHEMA,
                            "capture_point": ACT_CAPTURE,
                            "clock_domain": CLOCK,
                            "service_event": {
                                "t_ns": service["t_ns"],
                                "domain": service["domain"],
                                "service": service["service"],
                                "service_data": service["service_data"],
                                "context_id": service["context_id"],
                                "context_parent_id": service["context_parent_id"],
                            },
                            "parent_state_event": {
                                "t_ns": parent["t_ns"],
                                "entity_id": parent["entity_id"],
                                "old_state": parent["old_state"],
                                "new_state": parent["new_state"],
                                "context_id": parent["context_id"],
                                "context_parent_id": parent["context_parent_id"],
                            },
                        },
                    })

    if len(observations) != 144 or len(actions) != 72:
        raise AssertionError((len(observations), len(actions)))

    pack = {
        "schema": SCHEMA,
        "source_authority": dict(SOURCE),
        "selection_rule": (
            "For replicas 0 and 1, retain every timestamped *_snapshot field from every depth1/depth2 row; "
            "retain every climate.set_preset_mode service event and the unique retained state event whose "
            "context_id equals that service event's context_parent_id. No ReplayMark C1 output or expected "
            "semantic label is consulted during selection."
        ),
        "observations": observations,
        "actions": actions,
    }
    args.out.write_text(json.dumps(pack, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
