"""Supported package sources and signed-manifest verification.

ULI provisions its first supported distributions directly from official APT
repositories.  The signed ``InRelease`` file is verified *before* storage is
changed; debootstrap/apt then verifies every downloaded package against that
manifest chain while creating the target system.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

from uli.core.plan import DistroSelection


@dataclass(frozen=True)
class SourceInfo:
    distro_id: str
    variant: str
    version: str
    codename: str
    mirror: str
    inrelease_url: str
    keyring: str
    verification: str = "OpenPGP-signiertes APT InRelease + Paket-Hashes"

    def public_dict(self) -> dict[str, str]:
        data = asdict(self)
        data.pop("keyring", None)
        data["url"] = data.pop("mirror")
        return data


_BASE_SOURCES: dict[str, SourceInfo] = {
    "debian": SourceInfo(
        distro_id="debian",
        variant="",
        version="13",
        codename="trixie",
        mirror="https://deb.debian.org/debian",
        inrelease_url="https://deb.debian.org/debian/dists/trixie/InRelease",
        keyring="/usr/share/keyrings/debian-archive-keyring.gpg",
    ),
    "ubuntu": SourceInfo(
        distro_id="ubuntu",
        variant="",
        # This is an offline fallback.  A connected ULI session resolves the
        # current supported LTS from Canonical immediately before the plan is
        # created, so a point release never requires a new ULI ISO.
        version="26.04 LTS",
        codename="resolute",
        mirror="https://archive.ubuntu.com/ubuntu",
        inrelease_url="https://archive.ubuntu.com/ubuntu/dists/resolute/InRelease",
        keyring="/usr/share/keyrings/ubuntu-archive-keyring.gpg",
    ),
}

_UBUNTU_RELEASE_INDEX = "https://releases.ubuntu.com/releases/"
_UBUNTU_LTS_LINK = re.compile(
    r'href="(?P<suite>[a-z][a-z0-9-]*)/"[^>]*>\s*'
    r"Ubuntu\s+(?P<version>[0-9]+\.[0-9]+)(?:\.[0-9]+)?\s+LTS\b",
    re.IGNORECASE,
)
_SAFE_UBUNTU_SUITE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")


def _source_with_variant(source: SourceInfo, variant: str) -> SourceInfo:
    return SourceInfo(**{**asdict(source), "variant": variant})


def _current_ubuntu_lts(*, timeout: int = 8) -> SourceInfo:
    """Resolve Canonical's current LTS label, with a safe offline fallback.

    The release index only chooses a suite name.  The package source itself is
    still accepted only after its Ubuntu-keyring-signed ``InRelease`` has been
    verified, which prevents the index from authorising arbitrary packages.
    """

    fallback = _BASE_SOURCES["ubuntu"]
    request = urllib.request.Request(
        _UBUNTU_RELEASE_INDEX,
        headers={"User-Agent": "Ultimate-Linux-Installer/0.3"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if not response.geturl().lower().startswith("https://"):
                return fallback
            payload = response.read(512 * 1024 + 1)
    except (OSError, ValueError):
        return fallback
    if not payload or len(payload) > 512 * 1024:
        return fallback

    matches: list[tuple[tuple[int, int], str, str]] = []
    text = payload.decode("utf-8", errors="replace")
    for match in _UBUNTU_LTS_LINK.finditer(text):
        suite = match.group("suite").lower()
        version = match.group("version")
        if not _SAFE_UBUNTU_SUITE.fullmatch(suite):
            continue
        try:
            major, minor = (int(part) for part in version.split(".", 1))
        except ValueError:
            continue
        matches.append(((major, minor), version, suite))
    if not matches:
        return fallback
    _, version, suite = max(matches)
    mirror = fallback.mirror
    return SourceInfo(
        distro_id="ubuntu",
        variant="",
        version=f"{version} LTS",
        codename=suite,
        mirror=mirror,
        inrelease_url=f"{mirror}/dists/{suite}/InRelease",
        keyring=fallback.keyring,
    )


@lru_cache(maxsize=1)
def current_ubuntu_lts() -> SourceInfo:
    """Return the runtime-resolved current Ubuntu LTS for this ULI session."""

    return _current_ubuntu_lts()

SUPPORTED_SELECTIONS = {
    ("debian", "desktop"),
    ("debian", "server"),
    ("ubuntu", "desktop"),
    ("ubuntu", "server"),
}


def source_for(selection: DistroSelection) -> SourceInfo:
    key = (selection.id, selection.variant)
    if key not in SUPPORTED_SELECTIONS:
        raise ValueError(
            f"Distribution adapter is not released for real installation: "
            f"{selection.id}:{selection.variant}"
        )
    base = _BASE_SOURCES[selection.id]
    # A plan created in this session is pinned to the result from
    # ``current_ubuntu_lts``.  It must not silently change version between
    # source verification and debootstrap.
    if selection.id == "ubuntu":
        latest = current_ubuntu_lts()
        if not selection.release or selection.release.strip().casefold() in {
            latest.version.casefold(),
            latest.codename.casefold(),
        }:
            base = latest
    return _source_with_variant(base, selection.variant)


def current_source_for(selection: DistroSelection) -> SourceInfo:
    """Return the newest supported source for UI planning and verification."""

    if selection.id == "ubuntu":
        return _source_with_variant(current_ubuntu_lts(), selection.variant)
    return source_for(selection)


def verify_source_manifest(
    source: SourceInfo,
    cache_dir: Path,
    *,
    timeout: int = 45,
) -> Path:
    """Download and OpenPGP-verify an official APT InRelease manifest."""

    keyring = Path(source.keyring)
    if not keyring.is_file():
        raise RuntimeError(f"APT archive keyring is missing: {keyring}")
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(cache_dir, 0o700)
    request = urllib.request.Request(
        source.inrelease_url,
        headers={"User-Agent": "Ultimate-Linux-Installer/0.3"},
    )
    payload: bytes | None = None
    error: OSError | ValueError | None = None
    # DHCP and DNS can become ready a few seconds after NetworkManager marks a
    # device connected.  Retry transient lookup/connection failures before we
    # reject the plan; this remains entirely before any storage operation.
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if not response.geturl().lower().startswith("https://"):
                    raise RuntimeError("APT source redirected away from HTTPS")
                payload = response.read(8 * 1024 * 1024 + 1)
            break
        except RuntimeError:
            raise
        except (OSError, ValueError) as exc:
            error = exc
            if attempt < 2:
                time.sleep(2**attempt)
    if payload is None:
        raise RuntimeError(
            "Offizielle Paketquelle ist nicht erreichbar. "
            "Bitte Netzwerk und DNS-Verbindung prüfen: "
            f"{error}"
        ) from error
    if not payload or len(payload) > 8 * 1024 * 1024:
        raise RuntimeError(f"Invalid InRelease payload from {source.inrelease_url}")

    file_name = f"{source.distro_id}-{source.codename}-InRelease"
    destination = cache_dir / file_name
    fd, temporary_name = tempfile.mkstemp(prefix=f".{file_name}.", dir=cache_dir)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        result = subprocess.run(
            ["gpgv", "--keyring", str(keyring), str(temporary)],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"APT source signature verification failed for {source.distro_id}: "
                f"{(result.stderr or result.stdout).strip()}"
            )
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def verify_plan_sources(
    selections: list[DistroSelection],
    cache_dir: Path,
    *,
    progress: Callable[[int, int, SourceInfo], None] | None = None,
) -> list[Path]:
    """Verify each distinct distribution source used by a plan."""

    distinct: list[SourceInfo] = []
    seen: set[str] = set()
    for selection in selections:
        source = current_source_for(selection)
        if source.distro_id not in seen:
            distinct.append(source)
            seen.add(source.distro_id)
    verified: list[Path] = []
    total = len(distinct)
    for index, source in enumerate(distinct, start=1):
        if progress:
            progress(index - 1, total, source)
        verified.append(verify_source_manifest(source, cache_dir))
        if progress:
            progress(index, total, source)
    return verified
