from __future__ import annotations

"""Deterministically derive all HA-C2 shadow cells from the sealed C1 fixture pack.

Selection never consults a ReplayMark verdict or service preset outcome. It uses
only frozen depth1 provenance, initial motion condition, and monotonic timestamps.
Every historical carrier is from an earlier completed source episode in the same
replica as its target episode.
"""

from dataclasses import dataclass
from typing import Iterable

SCHEMA = "replaymark.ha-c2.shadow-cell.v1"


@dataclass(frozen=True)
class ShadowCell:
    cell_id: str
    family: str
    replica: int
    trial_ordinal: int
    decision_index: int
    source_row_index: int
    target_row_index: int
    historical_raw_action: dict[str, object]
    target_base_raw_observation: dict[str, object]
    target_parent_state_event: dict[str, object]
    target_direct_raw_action: dict[str, object]
    historical_timestamp_ns: int
    target_base_timestamp_ns: int

    def canonical_record(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "cell_id": self.cell_id,
            "family": self.family,
            "replica": self.replica,
            "trial_ordinal": self.trial_ordinal,
            "decision_index": self.decision_index,
            "source_row_index": self.source_row_index,
            "target_row_index": self.target_row_index,
            "historical_raw_action": self.historical_raw_action,
            "target_base_raw_observation": self.target_base_raw_observation,
            "target_parent_state_event": self.target_parent_state_event,
            "target_direct_raw_action": self.target_direct_raw_action,
            "historical_timestamp_ns": self.historical_timestamp_ns,
            "target_base_timestamp_ns": self.target_base_timestamp_ns,
        }


def _group(pack: dict[str, object]):
    obs: dict[tuple[int, str, int], dict[str, dict[str, object]]] = {}
    acts: dict[tuple[int, str, int], dict[int, dict[str, object]]] = {}
    for item in pack["observations"]:
        src = item["source"]
        key = (src["replica"], src["section"], src["row_index"])
        obs.setdefault(key, {})[src["field"]] = item["raw"]
    for item in pack["actions"]:
        src = item["source"]
        key = (src["replica"], src["section"], src["row_index"])
        acts.setdefault(key, {})[src["service_index"]] = item["raw"]
    return obs, acts


def _initial_motion(raw_observation: dict[str, object]) -> str:
    return raw_observation["snapshot"]["motion"]


def _ts_obs(raw_observation: dict[str, object]) -> int:
    return int(raw_observation["snapshot"]["t_ns"])


def _ts_action(raw_action: dict[str, object]) -> int:
    return int(raw_action["service_event"]["t_ns"])


def _depth1_rows(pack: dict[str, object], replica: int):
    obs, acts = _group(pack)
    rows = []
    keys = sorted(k for k in obs if k[0] == replica and k[1] == "depth1_rows")
    for key in keys:
        row_obs = obs[key]
        row_acts = acts[key]
        if set(row_obs) != {"initial_snapshot", "after_current_snapshot", "after_continuation_snapshot"}:
            raise AssertionError(("unexpected depth1 snapshot set", key, sorted(row_obs)))
        if set(row_acts) != {0, 1}:
            raise AssertionError(("unexpected depth1 service set", key, sorted(row_acts)))
        rows.append({
            "row_index": key[2],
            "observations": row_obs,
            "actions": row_acts,
            "motion": _initial_motion(row_obs["initial_snapshot"]),
            "initial_t_ns": _ts_obs(row_obs["initial_snapshot"]),
            "complete_t_ns": _ts_obs(row_obs["after_continuation_snapshot"]),
        })
    if len(rows) != 12:
        raise AssertionError(("depth1 row count", replica, len(rows)))
    return rows


def _monotone_pairs(source_rows, target_rows):
    available = []
    source_iter = iter(sorted(source_rows, key=lambda r: (r["complete_t_ns"], r["row_index"])))
    pending = next(source_iter, None)
    out = []
    for target in sorted(target_rows, key=lambda r: (r["initial_t_ns"], r["row_index"])):
        while pending is not None and pending["complete_t_ns"] < target["initial_t_ns"]:
            available.append(pending)
            pending = next(source_iter, None)
        if available:
            out.append((available.pop(0), target))
    return out


def build_shadow_cells(pack: dict[str, object]) -> list[ShadowCell]:
    if pack.get("schema") != "replaymark.ha-c1.archived-fixtures.v1":
        raise AssertionError("foreign C1 fixture schema")
    cells: list[ShadowCell] = []
    n2_ordinal = 0
    n2b_ordinal = 0
    for replica in (0, 1):
        rows = _depth1_rows(pack, replica)
        off = sorted((r for r in rows if r["motion"] == "off"), key=lambda r: (r["initial_t_ns"], r["row_index"]))
        on = sorted((r for r in rows if r["motion"] == "on"), key=lambda r: (r["initial_t_ns"], r["row_index"]))
        if len(off) != 6 or len(on) != 6:
            raise AssertionError(("motion strata", replica, len(off), len(on)))

        for local in range(1, len(off)):
            source, target = off[local - 1], off[local]
            hist = source["actions"][1]
            direct = target["actions"][0]
            if _ts_action(hist) >= target["initial_t_ns"]:
                raise AssertionError("N2 historical carrier is not temporally prior")
            cells.append(ShadowCell(
                cell_id=f"N2-r{replica}-t{local-1}", family="N2", replica=replica,
                trial_ordinal=n2_ordinal, decision_index=0,
                source_row_index=source["row_index"], target_row_index=target["row_index"],
                historical_raw_action=hist,
                target_base_raw_observation=target["observations"]["initial_snapshot"],
                target_parent_state_event=direct["parent_state_event"],
                target_direct_raw_action=direct,
                historical_timestamp_ns=_ts_action(hist),
                target_base_timestamp_ns=target["initial_t_ns"],
            ))
            n2_ordinal += 1

        pairs = _monotone_pairs(off, on)
        if len(pairs) != 5:
            raise AssertionError(("N2b chronological pair count", replica, len(pairs)))
        for local, (source, target) in enumerate(pairs):
            if source["complete_t_ns"] >= target["initial_t_ns"]:
                raise AssertionError("N2b source episode is not historical")
            for decision_index, (hist_index, base_field, direct_index) in enumerate(((0, "initial_snapshot", 0), (1, "after_current_snapshot", 1))):
                hist = source["actions"][hist_index]
                direct = target["actions"][direct_index]
                cells.append(ShadowCell(
                    cell_id=f"N2b-r{replica}-p{local}-d{decision_index}", family="N2b", replica=replica,
                    trial_ordinal=n2b_ordinal, decision_index=decision_index,
                    source_row_index=source["row_index"], target_row_index=target["row_index"],
                    historical_raw_action=hist,
                    target_base_raw_observation=target["observations"][base_field],
                    target_parent_state_event=direct["parent_state_event"],
                    target_direct_raw_action=direct,
                    historical_timestamp_ns=_ts_action(hist),
                    target_base_timestamp_ns=_ts_obs(target["observations"][base_field]),
                ))
            n2b_ordinal += 1

    if len([c for c in cells if c.family == "N2"]) != 10:
        raise AssertionError("C2 N2 cell count changed")
    if len([c for c in cells if c.family == "N2b"]) != 20:
        raise AssertionError("C2 N2b decision count changed")
    if len(cells) != 30:
        raise AssertionError("C2 total cell count changed")
    return cells


def cells_manifest(cells: Iterable[ShadowCell]) -> dict[str, object]:
    rows = list(cells)
    return {
        "schema": "replaymark.ha-c2.shadow-cell-manifest.v1",
        "selection": "N2 uses each motion-off target episode except the first with HOME carrier from the immediately preceding completed motion-off episode. N2b uses a chronology-only greedy one-to-one match from completed motion-off source episodes to later motion-on target episodes. Matching never reads service preset values or ReplayMark output.",
        "cells": [c.canonical_record() for c in rows],
    }


__all__ = ("ShadowCell", "build_shadow_cells", "cells_manifest")
