from __future__ import annotations

"""Deterministic wrapper used only by pre-science zero-stimulus qualification.

It freezes only the helper clock used to derive T02 input times. No trigger is
emitted, no Home Assistant timer is driven, and the selected scientific runtime
implementation remains ve2_scientific_native_execution_v2.py.
"""

from datetime import datetime as RealDateTime, timezone

import ve2_scientific_native_execution_v2  # installs the selected handoff repair
import ve2_scientific_native_execution_v1 as base


class FrozenInputDateTime(RealDateTime):
    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        value = cls(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)
        return value if tz is None else value.astimezone(tz)


base.datetime = FrozenInputDateTime

if __name__ == "__main__":
    base.main()
