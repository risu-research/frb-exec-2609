"""Public data transport preflight. No cohort data or bulk downloads.

Tests the state-published public file gateway using bounded requests only.
Outputs transport diagnostics, with no passwords, identifiers or source content.
"""
from __future__ import annotations
import datetime
import http.cookiejar
import json
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path

HOST = "sftp.floridados.gov"
PATHS = [
    "/",
    "/Public/doc/Quarterly/Cor/corevent.zip",
    "/doc/Quarterly/Cor/corevent.zip",
]
UA = "RISU-Public-Archive-Transport-Check/1.0"


def port_check(port, seconds=5):
    try:
        with socket.create_connection((HOST, port), timeout=seconds):
            return "reachable"
    except (OSError, TimeoutError) as e:
        return type(e).__name__


def http_check(path, method):
    req = urllib.request.Request("https://" + HOST + path,
                                 headers={"User-Agent": UA},
                                 method=method)
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    try:
        with opener.open(req, timeout=15) as response:
            return {"method": method, "path": path,
                    "status": response.status,
                    "content_type": response.headers.get("Content-Type"),
                    "content_length": response.headers.get("Content-Length"),
                    "final_host": response.url.split("/")[2],
                    "final_path": "/" + response.url.split("/", 3)[-1] if "/" in response.url[8:] else "/"}
    except urllib.error.HTTPError as e:
        return {"method": method, "path": path, "status": e.code,
                "content_type": e.headers.get("Content-Type"),
                "content_length": e.headers.get("Content-Length")}
    except Exception as e:
        return {"method": method, "path": path,
                "error": type(e).__name__, "detail": str(e)[:120]}


def main():
    out = {"checked_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
           "host": HOST,
           "ports": {str(port): port_check(port) for port in (22, 21, 443)},
           "http": [http_check("/", "GET")]
                 + [http_check(path, "HEAD") for path in PATHS[1:]]}
    Path("public_transport_probe.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
