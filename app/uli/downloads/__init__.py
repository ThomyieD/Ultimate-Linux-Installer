"""Release download helpers with checksum verification hooks."""

from __future__ import annotations

import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from uli.security.secrets import verify_sha256

ProgressCb = Callable[[int, int], None]


@dataclass
class DownloadItem:
    name: str
    url: str
    destination: Path
    sha256: str | None = None


def download_file(
    item: DownloadItem,
    *,
    timeout: int = 120,
    progress: ProgressCb | None = None,
) -> Path:
    item.destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = item.destination.with_suffix(item.destination.suffix + ".partial")
    req = urllib.request.Request(item.url, headers={"User-Agent": "Ultimate-Linux-Installer/0.2"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, tmp.open("wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        downloaded = 0
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
            downloaded += len(chunk)
            if progress:
                progress(downloaded, total)
    tmp.replace(item.destination)
    if item.sha256 and not verify_sha256(item.destination, item.sha256):
        item.destination.unlink(missing_ok=True)
        raise ValueError(f"Checksum mismatch for {item.name}")
    if progress:
        size = item.destination.stat().st_size
        progress(size, size)
    return item.destination
