#!/usr/bin/env python3
"""Discover official Florida corporate source vintages using read-only SFTP metadata."""
import json
from datetime import datetime,timezone
import paramiko
import sftp_download as public_source

PATHS=("/Public/doc/cor","/Public/doc/Quarterly/Cor")

def main():
    client=paramiko.Transport((public_source.HOST,22))
    client.banner_timeout=25
    client.auth_timeout=30
    client.connect(username=public_source.PUBLIC_USER,password=public_source.PUBLIC_PASSWORD)
    output={}
    try:
        sftp=paramiko.SFTPClient.from_transport(client)
        try:
            for path in PATHS:
                try:
                    listing=sftp.listdir_attr(path)
                    files=sorted(({"name":a.filename,"bytes":a.st_size,
                                   "modified_utc":datetime.fromtimestamp(a.st_mtime,timezone.utc).isoformat()}
                                  for a in listing),key=lambda a:(a["modified_utc"],a["name"]),reverse=True)
                    output[path]={"file_count":len(files),"latest_50":files[:50]}
                except OSError as error:
                    output[path]={"error_type":type(error).__name__}
        finally:sftp.close()
    finally:client.close()
    print(json.dumps({"source":"Florida DOS public SFTP file metadata",
                      "captured_at_utc":datetime.now(timezone.utc).isoformat(),
                      "paths":output},indent=2))

if __name__=="__main__":main()
