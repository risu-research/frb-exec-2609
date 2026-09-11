from __future__ import annotations

"""VE2 transport v6: exact Home Assistant start-trigger lifecycle repair.

V6 inherits the complete v5 transport implementation and changes exactly one
runtime semantic: the synthetic T02 `platform: homeassistant, event: start`
case emits Home Assistant 2026.9's source-proven EVENT_HOMEASSISTANT_STARTED
signal instead of the distinct EVENT_HOMEASSISTANT_START signal.

No bootstrap, registry, trigger definition, action definition, delay duration,
clock driver, wait timeout, state/state-for/time case, witness rule, or
transport pass criterion is changed.
"""

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED

import ve2_science_transport_qualify_v3 as v3
import ve2_science_transport_qualify_v4 as v4  # noqa: F401 - frozen inherited layer
import ve2_science_transport_qualify_v5 as v5

IMPLEMENTATION = "replaymark.ve2.science-transport-qualification-runtime.v6"
REPAIR_ID = "replaymark.ve2.t02-homeassistant-started-signal-repair.v1"
EXPECTED_T02_VERSION = "2026.9.0"
EXPECTED_OLD_SIGNAL = "homeassistant_start"
EXPECTED_NATIVE_SIGNAL = "homeassistant_started"


def _install_v6() -> None:
    # Install all already-qualified v5 behavior first.
    v5._install_v5()

    # Fail closed if the inherited source surface is not exactly the one that
    # was diagnosed. This is not a version-dependent fallback.
    if str(v3.EVENT_HOMEASSISTANT_START) != EXPECTED_OLD_SIGNAL:
        raise AssertionError(
            ("unexpected-inherited-start-signal", str(v3.EVENT_HOMEASSISTANT_START))
        )
    if str(EVENT_HOMEASSISTANT_STARTED) != EXPECTED_NATIVE_SIGNAL:
        raise AssertionError(
            ("unexpected-native-started-signal", str(EVENT_HOMEASSISTANT_STARTED))
        )

    # The v3 symbol has exactly one functional use: the lifecycle event emitted
    # inside run_startup_delay(). T01 roles never execute that function.
    v3.EVENT_HOMEASSISTANT_START = EVENT_HOMEASSISTANT_STARTED
    v3.IMPLEMENTATION = IMPLEMENTATION


def main() -> None:
    _install_v6()
    v3.main()


if __name__ == "__main__":
    main()
