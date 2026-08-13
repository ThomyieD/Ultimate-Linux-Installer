"""Resolve concrete ISO download URLs from adapter release metadata."""

from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass

from uli.core.adapters import get_adapter
from uli.core.plan import DistroSelection


@dataclass(frozen=True)
class IsoArtifact:
    name: str
    url: str
    sha256: str | None = None
    version: str = ""


def _fetch_text(url: str, *, timeout: int = 45) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Ultimate-Linux-Installer/0.2"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _parse_sha256sums(text: str, needle: str) -> tuple[str, str] | None:
    """Return (sha256, filename) for the first matching line."""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        digest, name = parts[0], parts[-1].lstrip("*")
        if needle in name and name.endswith(".iso"):
            return digest, name
    return None


def resolve_iso(selection: DistroSelection) -> IsoArtifact:
    adapter = get_adapter(selection.id)
    meta = adapter.resolve_release(selection)
    distro = selection.id

    if distro == "ubuntu":
        flavor = "desktop" if selection.variant == "desktop" else "live-server"
        base = str(meta.get("mirror") or "https://releases.ubuntu.com/24.04/").rstrip("/") + "/"
        sums_url = str(meta.get("checksum_url") or base + "SHA256SUMS")
        sums = _fetch_text(sums_url)
        match = _parse_sha256sums(sums, flavor)
        if not match:
            match = _parse_sha256sums(sums, "amd64")
        if not match:
            raise RuntimeError(f"Ubuntu ISO not found in {sums_url}")
        digest, filename = match
        return IsoArtifact(
            name=filename,
            url=base + filename,
            sha256=digest,
            version=str(meta.get("version") or ""),
        )

    if distro == "debian":
        # Official netinst AMD64
        base = "https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/"
        sums = _fetch_text(base + "SHA256SUMS")
        match = _parse_sha256sums(sums, "netinst")
        if not match:
            raise RuntimeError("Debian netinst ISO not found")
        digest, filename = match
        return IsoArtifact(name=filename, url=base + filename, sha256=digest, version="current")

    if distro == "fedora":
        version = str(meta.get("version") or "42")
        # Workstation live ISO via mirror redirector-friendly path
        filename = f"Fedora-Workstation-Live-x86_64-{version}-1.1.iso"
        url = (
            "https://download.fedoraproject.org/pub/fedora/linux/releases/"
            f"{version}/Workstation/x86_64/iso/{filename}"
        )
        return IsoArtifact(name=filename, url=url, sha256=None, version=version)

    if distro == "arch":
        base = str(meta.get("bootstrap") or "https://geo.mirror.pkgbuild.com/iso/latest/").rstrip("/") + "/"
        sums = _fetch_text(base + "sha256sums.txt")
        match = _parse_sha256sums(sums, "x86_64")
        if not match:
            # Fallback filename pattern
            raise RuntimeError("Arch ISO not found in sha256sums.txt")
        digest, filename = match
        return IsoArtifact(name=filename, url=base + filename, sha256=digest, version="rolling")

    if distro == "proxmox":
        # Proxmox VE ISO landing — use a stable current path pattern
        page = _fetch_text("https://enterprise.proxmox.com/iso/")
        found = re.findall(r'href="(proxmox-ve_[0-9.]+\.iso)"', page)
        if not found:
            # public download mirror
            page = _fetch_text("https://www.proxmox.com/en/downloads")
            found = re.findall(r"(proxmox-ve_[0-9.]+\.iso)", page)
        if not found:
            raise RuntimeError("Proxmox ISO filename could not be resolved")
        filename = found[0]
        url = f"https://enterprise.proxmox.com/iso/{filename}"
        return IsoArtifact(name=filename, url=url, sha256=None, version="")

    raise RuntimeError(f"No ISO resolver for distro {distro}")
