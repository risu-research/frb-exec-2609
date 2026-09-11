from __future__ import annotations

"""VE2 transport v5: evidence-projection-only successor to v4.

V4's registry-closed native substrate passed on all three frozen Home Assistant
runtimes, but the inherited v3 _fresh_hass evidence projection omitted the
already-produced substrate['registries'] proof object.  V5 changes no Home
Assistant setup call, registry load, neutral trigger/action, clock transport,
or scientific input surface.  It captures the exact registry proof returned by
v4 for the same HomeAssistant object and projects that exact object once into
the inherited bootstrap_adapter before canonical hashing/serialization.
"""

from typing import Any

import ve2_science_transport_qualify_v3 as v3
import ve2_science_transport_qualify_v4 as v4

IMPLEMENTATION = "replaymark.ve2.science-transport-qualification-runtime.v5"
PROJECTION_ID = "replaymark.ve2.registry-witness-exact-object-projection.v1"

# id(hass) -> (exact hass object, exact registries proof object)
_PENDING: dict[int, tuple[Any, dict[str, Any]]] = {}
_ORIGINAL_FRESH_HASS = v3._fresh_hass


async def _prepare_native_substrate_v5(hass: Any, imports: dict[str, Any]) -> dict[str, Any]:
    substrate = await v4._prepare_native_substrate_v4(hass, imports)
    registries = substrate.get("registries")
    if not isinstance(registries, dict):
        raise AssertionError("v4 substrate omitted registries proof")
    key = id(hass)
    if key in _PENDING:
        raise AssertionError("duplicate unconsumed registry witness for HomeAssistant object")
    _PENDING[key] = (hass, registries)
    return substrate


async def _fresh_hass_v5(*args: Any, **kwargs: Any):
    result = await _ORIGINAL_FRESH_HASS(*args, **kwargs)
    hass, temp, observer, entity, adapter, trace_api = result
    key = id(hass)
    pending = _PENDING.pop(key, None)
    if pending is None:
        raise AssertionError("missing same-HASS registry witness at evidence projection")
    owner, registries = pending
    if owner is not hass:
        raise AssertionError("stale/reused HomeAssistant identity for registry witness")
    if "registries" in adapter:
        raise AssertionError("registry witness already projected")

    prior_adapter_sha256 = adapter.pop("adapter_sha256", None)
    if not isinstance(prior_adapter_sha256, str) or len(prior_adapter_sha256) != 64:
        raise AssertionError("missing inherited pre-projection adapter digest")

    # Exact same object, not reconstructed/copied from post-run state.
    adapter["registries"] = registries
    adapter["evidence_projection"] = {
        "projection_id": PROJECTION_ID,
        "source": "exact substrate['registries'] object returned for same HomeAssistant instance",
        "same_hass_object_identity": True,
        "consumed_exactly_once": True,
        "manual_witness_reconstruction": False,
        "additional_home_assistant_setup_calls": 0,
        "execution_semantics_changed_from_v4": False,
        "prior_adapter_sha256": prior_adapter_sha256,
        "result_dependent_fallback": False,
        "retry_after_failure": False,
    }
    adapter["adapter_sha256"] = v3._sha(
        {k: value for k, value in adapter.items() if k != "adapter_sha256"}
    )
    return hass, temp, observer, entity, adapter, trace_api


def _install_v5() -> None:
    v3.IMPLEMENTATION = IMPLEMENTATION
    v3._prepare_native_substrate = _prepare_native_substrate_v5
    v3._fresh_hass = _fresh_hass_v5


def main() -> None:
    _install_v5()
    v3.main()


if __name__ == "__main__":
    main()
