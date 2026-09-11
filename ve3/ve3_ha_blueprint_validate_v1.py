#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.blueprint.models import Blueprint
from homeassistant.util import yaml as yaml_util


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: validator.py MANIFEST RESULT")
    manifest_path = Path(sys.argv[1])
    result_path = Path(sys.argv[2])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    result = {}
    for item in manifest:
        key = item["key"]
        path = Path("/work") / item["relative_path"]
        rec = {"ok": False, "error": None, "domain": None, "name": None}
        try:
            data = yaml_util.load_yaml_dict(path)
            bp = Blueprint(
                data,
                expected_domain="automation",
                path=item["relative_path"],
                schema=AUTOMATION_BLUEPRINT_SCHEMA,
            )
            errors = bp.validate()
            if errors:
                rec["error"] = "Blueprint.validate: " + " | ".join(errors)
            else:
                rec["ok"] = True
                rec["domain"] = bp.domain
                rec["name"] = bp.name
        except Exception as exc:
            rec["error"] = f"{type(exc).__name__}: {exc}"
        result[key] = rec
    result_path.write_text(
        json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
