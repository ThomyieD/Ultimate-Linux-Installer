"""Release download helpers with checksum verification hooks."""

from __future__ import annotations

import urllib.request
from dataclasses import dataclass
from pathlib import Path

from uli.security.secrets import verify_sha256


@dataclass
class DownloadItem:
    name: str
    url: str
    destination: Path
    sha256: str | None = None


def download_file(item: DownloadItem, *, timeout: int = 60) -> Path:
    item.destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(item.url, timeout=timeout) as resp, item.destination.open("wb") as out:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
    if item.sha256 and not verify_sha256(item.destination, item.sha256):
        item.destination.unlink(missing_ok=True)
        raise ValueError(f"Checksum mismatch for {item.name}")
    return item.destination
