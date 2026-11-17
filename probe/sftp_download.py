"""Download one official public source ZIP over authenticated SFTP.

The state publishes these public credentials and file paths. The caller pins
the archive digest. No raw contents or selected IDs are printed or published.
"""
import hashlib
import sys
from pathlib import Path
import paramiko

HOST = "sftp.floridados.gov"
PUBLIC_USER = "Public"
PUBLIC_PASSWORD = "PubAccess1845!"
SOURCES = {
    "corevent": ("corevent.zip", "395c5240b2eddabf5300b09c658c93320a1e9a311a4897983526d8dc1152280d"),
    "cordata": ("cordata.zip", "f85264b1443a7f60c8a95ec69bebc9407cc87367fe5acef59a17b58068d5bee9"),
}


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in SOURCES:
        raise SystemExit("Usage: sftp_download.py corevent|cordata LOCAL_OUTPUT")
    item, local = sys.argv[1], Path(sys.argv[2])
    name, expected = SOURCES[item]
    remote = "/Public/doc/Quarterly/Cor/" + name
    local.parent.mkdir(parents=True, exist_ok=True)
    if local.exists():
        raise SystemExit("Refusing to overwrite an existing source file")
    t = paramiko.Transport((HOST, 22))
    t.banner_timeout = 20
    t.auth_timeout = 25
    t.set_keepalive(30)
    try:
        t.connect(username=PUBLIC_USER, password=PUBLIC_PASSWORD)
        sftp = paramiko.SFTPClient.from_transport(t)
        try:
            size = sftp.stat(remote).st_size
            if not 100_000_000 <= size <= 3_000_000_000:
                raise RuntimeError("Unexpected source archive size")
            print("Authenticated SFTP source", item, "size", size, flush=True)
            sftp.get(remote, str(local), prefetch=True,
                     max_concurrent_prefetch_requests=48)
        finally:
            sftp.close()
    finally:
        t.close()
    h = hashlib.sha256()
    with local.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4*1024*1024), b""):
            h.update(chunk)
    actual = h.hexdigest()
    print("Downloaded SHA256", item, actual, flush=True)
    if actual != expected:
        local.unlink(missing_ok=True)
        raise ValueError("The public source archive changed. Frozen source digest is different.")
    print("Source SHA-256 matched the previously frozen evidence.", flush=True)


if __name__ == "__main__":
    main()
