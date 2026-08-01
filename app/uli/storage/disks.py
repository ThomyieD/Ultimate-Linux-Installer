from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from uli.storage.layout import DiskInfo


def _read_cmdline() -> str:
    try:
        return Path("/proc/cmdline").read_text(encoding="utf-8")
    except OSError:
        return ""


def detect_installation_medium_paths() -> set[str]:
    """Best-effort detection of the boot USB so it is never offered as a target."""
    mediums: set[str] = set()
    cmdline = _read_cmdline()
    for token in cmdline.split():
        if token.startswith("live-media-path=") or token.startswith("bootfrom="):
            mediums.add(token.split("=", 1)[1])

    # Find mounts under /run/live or labeled ULI
    try:
        result = subprocess.run(
            ["findmnt", "-J", "-o", "SOURCE,TARGET,LABEL,PARTLABEL"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout:
            data = json.loads(result.stdout)
            for entry in data.get("filesystems", []):
                target = entry.get("target") or ""
                label = (entry.get("label") or "") + (entry.get("partlabel") or "")
                source = entry.get("source") or ""
                if "live" in target or "ULI" in label.upper() or "ULTIMATE" in label.upper():
                    # Normalize to whole disk later
                    mediums.add(source)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return mediums


def _lsblk_json() -> dict:
    if not shutil.which("lsblk"):
        return {"blockdevices": []}
    result = subprocess.run(
        [
            "lsblk",
            "-J",
            "-b",
            "-o",
            "NAME,PATH,SIZE,MODEL,SERIAL,TRAN,RM,TYPE,MOUNTPOINT",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def list_candidate_disks(*, include_removable: bool = False) -> list[DiskInfo]:
    """Return internal disks suitable as installation targets."""
    raw = _lsblk_json()
    medium_sources = detect_installation_medium_paths()
    disks: list[DiskInfo] = []

    for dev in raw.get("blockdevices", []):
        if dev.get("type") != "disk":
            continue
        path = dev.get("path") or f"/dev/{dev.get('name')}"
        size = int(dev.get("size") or 0)
        removable = bool(int(dev.get("rm") or 0))
        transport = (dev.get("tran") or "").lower()
        is_usb = transport == "usb" or removable

        # Skip obvious installation medium / loop / small devices
        if path in medium_sources or any(path.startswith(m) for m in medium_sources if m.startswith("/dev/")):
            continue
        if size < 16 * 1024**3:
            continue
        if is_usb and not include_removable:
            continue

        disks.append(
            DiskInfo(
                id=f"{dev.get('serial') or dev.get('name')}-{size}",
                path=path,
                size_bytes=size,
                model=(dev.get("model") or "").strip(),
                serial=(dev.get("serial") or "").strip(),
                transport=transport,
                is_removable=is_usb,
                is_installation_medium=False,
            )
        )
    return disks


def simulated_disks() -> list[DiskInfo]:
    """Disks for desktop development / CI without touching real hardware."""
    return [
        DiskInfo(
            id="sim-nvme-512",
            path="/dev/disk/by-id/ulli-simulated-nvme",
            size_bytes=512 * 1024**3,
            model="ULI Simulated NVMe 512G",
            serial="SIMNVME512",
            transport="nvme",
        ),
        DiskInfo(
            id="sim-ssd-256",
            path="/dev/disk/by-id/ulli-simulated-ssd",
            size_bytes=256 * 1024**3,
            model="ULI Simulated SSD 256G",
            serial="SIMSSD256",
            transport="sata",
        ),
    ]


def get_disks(*, simulate: bool | None = None) -> list[DiskInfo]:
    if simulate is None:
        simulate = os.environ.get("ULI_SIMULATE_DISK", "1") == "1"
    if simulate:
        return simulated_disks()
    real = list_candidate_disks()
    return real or simulated_disks()
