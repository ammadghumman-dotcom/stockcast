"""Tiny S3 helper for backups (boto3): put / get / prune. Works with R2/B2 via --endpoint-url."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse


def _client(endpoint: str | None):
    import boto3

    return boto3.client("s3", endpoint_url=endpoint or None)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["put", "get", "prune"])
    ap.add_argument("src")
    ap.add_argument("dst", nargs="?")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--endpoint-url", default=None)
    a = ap.parse_args()
    s3 = _client(a.endpoint_url)
    if a.cmd == "put":
        u = urlparse(a.dst)
        s3.upload_file(a.src, u.netloc, u.path.lstrip("/"))
        print(f"uploaded {a.dst}")
    elif a.cmd == "get":
        u = urlparse(a.src)
        s3.download_file(u.netloc, u.path.lstrip("/"), a.dst)
        print(f"downloaded {a.dst}")
    else:
        u = urlparse(a.src)
        cutoff = datetime.now(UTC) - timedelta(days=a.days)
        pages = s3.get_paginator("list_objects_v2").paginate(
            Bucket=u.netloc, Prefix=u.path.lstrip("/")
        )
        old = [
            o["Key"]
            for page in pages
            for o in page.get("Contents", [])
            if o["LastModified"] < cutoff
        ]
        for i in range(0, len(old), 1000):
            s3.delete_objects(
                Bucket=u.netloc, Delete={"Objects": [{"Key": k} for k in old[i : i + 1000]]}
            )
        print(f"pruned {len(old)} objects older than {a.days} days")


if __name__ == "__main__":
    main()
