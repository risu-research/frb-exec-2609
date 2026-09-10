from __future__ import print_function

import importlib
import importlib.util
import json
import os
import platform
import re
import sys
import traceback

OUT = os.environ.get("VE2_PROBE_OUT", "/result.json")
ROOT = "/probe"

def requirement_import(req):
    m = re.match(r"^\s*([A-Za-z0-9_.-]+)", req)
    name = m.group(1) if m else None
    module = name.replace("-", "_") if name else None
    return name, module

def syntax_check_tree(root):
    count = 0
    for base, _dirs, files in os.walk(root):
        for filename in sorted(files):
            if not filename.endswith(".py"):
                continue
            path = os.path.join(base, filename)
            source = open(path, "rb").read()
            compile(source, path, "exec")
            count += 1
    return count

def main():
    result = {
        "schema": "replaymark.ve2.runtime-inside-probe.v1",
        "status": "FAIL",
        "scientific_result_opened": False,
        "transition_fixture_executed": False,
        "historical_action_dispatched": False,
    }
    try:
        sys.path.insert(0, ROOT)
        import homeassistant.const as ha_const
        ha_version = getattr(ha_const, "__version__", None)
        if not ha_version:
            try:
                from importlib import metadata
                ha_version = metadata.version("homeassistant")
            except Exception:
                ha_version = "UNKNOWN"
        result["home_assistant_version"] = str(ha_version)
        result["python_version"] = platform.python_version()

        comp = os.path.join(ROOT, "custom_components", "better_thermostat")
        manifest = json.load(open(os.path.join(comp, "manifest.json"), "r"))
        result["component_manifest_version"] = manifest.get("version")
        requirements = list(manifest.get("requirements") or [])
        req_results = []
        for req in requirements:
            name, module = requirement_import(req)
            ok = bool(module and importlib.util.find_spec(module) is not None)
            req_results.append({"requirement": req, "distribution_hint": name, "import_name": module, "importable": ok})
            if not ok:
                raise RuntimeError("requirement-not-importable:" + str(req))
        result["requirements"] = req_results

        result["syntax_checked_python_files"] = syntax_check_tree(comp)

        imported = []
        for module in (
            "custom_components.better_thermostat",
            "custom_components.better_thermostat.const",
            "custom_components.better_thermostat.climate",
        ):
            importlib.import_module(module)
            imported.append(module)
        result["imported_modules"] = imported
        result["status"] = "PASS"
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)
        result["traceback"] = traceback.format_exc()

    with open(OUT, "w") as f:
        json.dump(result, f, sort_keys=True, indent=2)
        f.write("\n")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 3

if __name__ == "__main__":
    sys.exit(main())
