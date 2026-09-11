from __future__ import annotations

"""VE2 transport v6: source-correct Home Assistant start lifecycle repair.

V6 inherits the complete v5 transport implementation and makes only the two
coupled adaptations required by Home Assistant 2026.9's native `platform:
homeassistant, event: start` semantics:

1. emit EVENT_HOMEASSISTANT_STARTED, the exact signal the native trigger arms;
2. mark synthetic event-root parent binding as not applicable for this trigger
   family, because the native start-trigger callback does not pass the event
   Context into the automation action.

No Home Assistant setup, registry loading, trigger/action definition, delay,
clock driver, wait timeout, state/state-for/time case, native witness capture,
or transport pass criterion is changed.
"""

from typing import Any

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED

import ve2_science_transport_qualify_v3 as v3
import ve2_science_transport_qualify_v4 as v4  # noqa: F401 - frozen inherited layer
import ve2_science_transport_qualify_v5 as v5

IMPLEMENTATION = "replaymark.ve2.science-transport-qualification-runtime.v6"
REPAIR_ID = "replaymark.ve2.t02-homeassistant-start-lifecycle-repair.v1"
EXPECTED_OLD_SIGNAL = "homeassistant_start"
EXPECTED_NATIVE_SIGNAL = "homeassistant_started"
STARTUP_CASE = "homeassistant_start_delay_30s"
STARTUP_FAMILY = "HOMEASSISTANT_START"

_ORIGINAL_COLLECT_CASE = v3._collect_case


async def _collect_case_v6(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Delegate unchanged witness collection with source-correct applicability.

    The v3 caller supplies a synthetic event Context for its raw lifecycle
    emission. Home Assistant's native 2026.9 start-trigger callback ignores the
    Event argument and invokes the automation action without a Context. Thus
    parent binding to that synthetic raw-event Context is not a native invariant
    for this trigger family. The frozen independent validator already encodes
    this as `root_context_id is None -> not applicable`.
    """
    case = args[0] if args else kwargs.get("case")
    family = args[1] if len(args) > 1 else kwargs.get("expected_family")
    if case == STARTUP_CASE:
        if family != STARTUP_FAMILY:
            raise AssertionError(("startup-family-drift", family))
        if "root_context_id" not in kwargs or kwargs["root_context_id"] is None:
            raise AssertionError("expected inherited synthetic startup root context")
        kwargs = dict(kwargs)
        kwargs["root_context_id"] = None
    return await _ORIGINAL_COLLECT_CASE(*args, **kwargs)


def _install_v6() -> None:
    # Install all already-qualified v5 bootstrap/registry/evidence behavior.
    v5._install_v5()

    # Fail closed unless the inherited and native lifecycle surfaces are exactly
    # the prospectively diagnosed ones. There is no fallback or retry.
    if str(v3.EVENT_HOMEASSISTANT_START) != EXPECTED_OLD_SIGNAL:
        raise AssertionError(
            ("unexpected-inherited-start-signal", str(v3.EVENT_HOMEASSISTANT_START))
        )
    if str(EVENT_HOMEASSISTANT_STARTED) != EXPECTED_NATIVE_SIGNAL:
        raise AssertionError(
            ("unexpected-native-started-signal", str(EVENT_HOMEASSISTANT_STARTED))
        )

    # v3's signal symbol has exactly one functional use, inside
    # run_startup_delay(). T01 roles never execute that function.
    v3.EVENT_HOMEASSISTANT_START = EVENT_HOMEASSISTANT_STARTED

    # The collector algorithm is untouched; only startup-family applicability
    # of a synthetic root-parent obligation is corrected before delegation.
    v3._collect_case = _collect_case_v6
    v3.IMPLEMENTATION = IMPLEMENTATION


def main() -> None:
    _install_v6()
    v3.main()


if __name__ == "__main__":
    main()
