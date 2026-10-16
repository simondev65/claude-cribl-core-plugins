#!/usr/bin/env python3
"""Fetch official Cribl documentation with a persistent one-week cache."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "cribl-docs"
ALLOWED_HOST = "docs.cribl.io"


def validate_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
        raise ValueError(f"only https://{ALLOWED_HOST}/ URLs are allowed")


def cache_paths(url: str, cache_dir: Path) -> tuple[Path, Path]:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    suffix = ".txt" if urllib.parse.urlparse(url).path.endswith(".txt") else ".md"
    return cache_dir / f"{digest}{suffix}", cache_dir / f"{digest}.json"


def read_metadata(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def write_atomic(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def write_metadata(path: Path, metadata: dict) -> None:
    write_atomic(
        path,
        (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )


def is_fresh(content_path: Path, metadata: dict, now: float) -> bool:
    fetched_at = metadata.get("fetched_at")
    return (
        content_path.is_file()
        and isinstance(fetched_at, (int, float))
        and 0 <= now - fetched_at < CACHE_TTL_SECONDS
    )


def fetch_document(url: str, cache_dir: Path, refresh: bool = False) -> tuple[Path, str]:
    validate_url(url)
    cache_dir.mkdir(parents=True, exist_ok=True)
    content_path, metadata_path = cache_paths(url, cache_dir)
    metadata = read_metadata(metadata_path)
    now = time.time()

    if not refresh and is_fresh(content_path, metadata, now):
        return content_path, "hit"

    headers = {"User-Agent": "cribl-docs-cache/1.0"}
    if content_path.is_file():
        if metadata.get("etag"):
            headers["If-None-Match"] = metadata["etag"]
        if metadata.get("last_modified"):
            headers["If-Modified-Since"] = metadata["last_modified"]

    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            content = response.read()
            if not content:
                raise RuntimeError("the documentation server returned an empty response")
            write_atomic(content_path, content)
            write_metadata(
                metadata_path,
                {
                    "etag": response.headers.get("ETag"),
                    "fetched_at": now,
                    "last_modified": response.headers.get("Last-Modified"),
                    "url": url,
                },
            )
            return content_path, "refreshed"
    except urllib.error.HTTPError as error:
        if error.code == 304 and content_path.is_file():
            metadata.update({"fetched_at": now, "url": url})
            write_metadata(metadata_path, metadata)
            return content_path, "validated"
        if content_path.is_file():
            return content_path, f"stale (HTTP {error.code})"
        raise
    except (OSError, RuntimeError, urllib.error.URLError) as error:
        if content_path.is_file():
            return content_path, f"stale ({error})"
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch a docs.cribl.io page with a one-week persistent cache."
    )
    parser.add_argument("url", help="Official https://docs.cribl.io/ URL")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE_DIR,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Revalidate now instead of waiting for the one-week TTL.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        path, status = fetch_document(args.url, args.cache_dir, args.refresh)
    except (OSError, RuntimeError, ValueError, urllib.error.URLError) as error:
        print(f"cribl-docs-cache: {error}", file=sys.stderr)
        return 1

    print(path)
    print(f"cribl-docs-cache: {status}; TTL={CACHE_TTL_SECONDS}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
