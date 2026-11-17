"""Authenticate to state-published public archive endpoints.

Only public-account access, directory metadata and headers are queried.
No archive bytes or entity content are written to the public repository.
"""
from __future__ import annotations

import base64
import datetime
import ftplib
import json
import ssl
import urllib.error
import urllib.request
from pathlib import Path

HOST = "sftp.floridados.gov"
PUBLIC_USER = "Public"
PUBLIC_PASS = "PubAccess1845!"
TARGETS = [
    "/doc/quarterly/cor/corevent.zip",
    "/doc/Quarterly/Cor/corevent.zip",
    "/Public/doc/Quarterly/Cor/corevent.zip",
]


def report_exception(exc):
    return type(exc).__name__


def check_https(path):
    basic = base64.b64encode((PUBLIC_USER + ":" + PUBLIC_PASS).encode()).decode()
    req = urllib.request.Request(
        "https://" + HOST + path,
        method="HEAD",
        headers={"Authorization": "Basic " + basic,
                 "User-Agent": "PublicArchiveMetadata/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return {"path": path, "status": response.status,
                    "content_length": response.headers.get("Content-Length"),
                    "content_type": response.headers.get("Content-Type")}
    except urllib.error.HTTPError as exc:
        return {"path": path, "status": exc.code}
    except Exception as exc:
        return {"path": path, "error": report_exception(exc)}


def check_ftps():
    data = {"transport": "explicit_ftps_21", "auth": "not_attempted"}
    ftp = ftplib.FTP_TLS(context=ssl.create_default_context(), timeout=18)
    try:
        ftp.connect(HOST, 21, timeout=18)
        ftp.login(PUBLIC_USER, PUBLIC_PASS)  # FTP_TLS upgrades control connection first.
        data["auth"] = "success"
        ftp.prot_p()
        data["pwd"] = ftp.pwd()
        for path in ("/doc/quarterly/cor", "/doc/Quarterly/Cor", "/Public/doc/Quarterly/Cor"):
            try:
                ftp.cwd(path)
                data["target_directory"] = ftp.pwd()
                data["files"] = {name: ftp.size(name)
                                 for name in ("corevent.zip", "cordata.zip")}
                break
            except Exception as exc:
                data.setdefault("directory_errors", []).append({"path": path, "type": report_exception(exc)})
    except Exception as exc:
        data["error"] = report_exception(exc)
    finally:
        try:
            ftp.close()
        except Exception:
            pass
    return data


def check_sftp():
    data = {"transport": "sftp_22", "auth": "not_attempted"}
    try:
        import paramiko
        session = paramiko.Transport((HOST, 22))
        session.banner_timeout = 20
        session.auth_timeout = 20
        try:
            session.connect(username=PUBLIC_USER, password=PUBLIC_PASS)
            data["auth"] = "success"
            client = paramiko.SFTPClient.from_transport(session)
            try:
                data["cwd"] = client.normalize(".")
                for path in (".", "doc/Quarterly/Cor", "/doc/Quarterly/Cor",
                             "/Public/doc/Quarterly/Cor", "doc/quarterly/cor"):
                    try:
                        entries = client.listdir_attr(path)
                        data.setdefault("available_directories", []).append(
                            {"path": path, "entries": [
                                {"name": a.filename, "size": a.st_size}
                                for a in entries if a.filename in (
                                    "doc", "Doc", "Public", "Quarterly", "quarterly", "Cor", "cor",
                                    "corevent.zip", "cordata.zip")]})
                    except (OSError, IOError):
                        continue
            finally:
                client.close()
        finally:
            session.close()
    except Exception as exc:
        data["error"] = report_exception(exc)
    return data


def main():
    result = {"checked_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "source_host": HOST,
              "https_basic_auth": [check_https("/")]+[check_https(p) for p in TARGETS],
              "ftps": check_ftps(),
              "sftp": check_sftp()}
    Path("public_archive_auth.json").write_text(json.dumps(result, sort_keys=True, indent=2)+"\n")
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
