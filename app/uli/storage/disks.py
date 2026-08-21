from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import stat
import struct
import subprocess
from pathlib import Path

from uli.storage.layout import DiskInfo

BLKGETDISKSEQ = 0x80081280


def get_disk_sequence(fd: int) -> int:
    """Return the kernel instance sequence for an open block-device FD."""
    buffer = bytearray(8)
    fcntl.ioctl(fd, BLKGETDISKSEQ, buffer, True)
    return int(struct.unpack("=Q", buffer)[0])


def read_disk_sequence(path: str) -> int:
    """Best-effort disk sequence lookup used while enumerating candidates."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return 0
    try:
        return get_disk_sequence(fd)
    except OSError:
        return 0
    finally:
        os.close(fd)

_BY_ID_PARTITION_SUFFIX = re.compile(r"-part[0-9]+$")
_SAFE_BY_ID_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]*$")
_BY_ID_PREFERENCE = (
    "wwn-",
    "nvme-eui.",
    "nvme-uuid.",
    "ata-",
    "scsi-",
    "virtio-",
    "nvme-",
    "usb-",
)


def find_stable_disk_path(
    disk_path: str,
    *,
    by_id_root: str | Path = "/dev/disk/by-id",
) -> str | None:
    """Return a non-partition ``by-id`` alias bound to the same block device.

    Kernel names such as ``/dev/sda`` can be reused after a hot-unplug.  The
    destructive executor therefore operates through a udev identity alias and
    rechecks that alias before every command.
    """
    try:
        target = os.stat(disk_path)
    except OSError:
        return None
    if not stat.S_ISBLK(target.st_mode):
        return None

    root = Path(by_id_root)
    try:
        entries = list(root.iterdir())
    except OSError:
        return None

    matches: list[Path] = []
    for entry in entries:
        if (
            not _SAFE_BY_ID_NAME.fullmatch(entry.name)
            or _BY_ID_PARTITION_SUFFIX.search(entry.name)
            or not entry.is_symlink()
        ):
            continue
        try:
            candidate = os.stat(entry)
        except OSError:
            continue
        if stat.S_ISBLK(candidate.st_mode) and candidate.st_rdev == target.st_rdev:
            matches.append(entry)
    if not matches:
        return None

    def rank(entry: Path) -> tuple[int, int, str]:
        preference = next(
            (index for index, prefix in enumerate(_BY_ID_PREFERENCE) if entry.name.startswith(prefix)),
            len(_BY_ID_PREFERENCE),
        )
        return preference, len(entry.name), entry.name

    return str(min(matches, key=rank))


def _walk_devices(entries: list[dict]) -> list[dict]:
    walked: list[dict] = []
    for entry in entries:
        walked.append(entry)
        children = entry.get("children") or []
        if isinstance(children, list):
            walked.extend(_walk_devices([child for child in children if isinstance(child, dict)]))
    return walked


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
        if token.startswith(("live-media-path=", "bootfrom=")):
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
            for entry in _walk_devices(data.get("filesystems", [])):
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
            "NAME,PATH,SIZE,MODEL,SERIAL,WWN,MAJ:MIN,TRAN,RM,TYPE,MOUNTPOINT",
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
    canonical_media = {
        os.path.realpath(source)
        for source in medium_sources
        if isinstance(source, str) and source.startswith("/dev/")
    }
    disks: list[DiskInfo] = []

    for dev in raw.get("blockdevices", []):
        if dev.get("type") != "disk":
            continue
        path = dev.get("path") or f"/dev/{dev.get('name')}"
        size = int(dev.get("size") or 0)
        removable = bool(int(dev.get("rm") or 0))
        transport = (dev.get("tran") or "").lower()
        is_usb = transport == "usb" or removable

        # A destructive plan must be bound to an identity that survives device
        # renumbering. Model/size/MAJ:MIN alone cannot distinguish a hot-swap.
        serial = (dev.get("serial") or "").strip()
        wwn = (dev.get("wwn") or "").strip()
        if not serial and not wwn:
            continue

        tree_paths = {
            os.path.realpath(str(entry.get("path")))
            for entry in _walk_devices([dev])
            if entry.get("path")
        }

        # Skip the whole parent disk when any child is the mounted live medium.
        if tree_paths & canonical_media:
            continue
        if size < 8 * 1024**3:
            continue
        if is_usb and not include_removable:
            continue

        stable_path = find_stable_disk_path(path)
        if stable_path is None:
            # Serial/WWN metadata is not enough if every later command would
            # still target a reusable kernel name such as /dev/sda.
            continue
        disk_sequence = read_disk_sequence(stable_path)
        if disk_sequence <= 0:
            # A positive BLKGETDISKSEQ value is required to distinguish reuse
            # of the same MAJ:MIN by a newly attached block-device instance.
            continue

        disks.append(
            DiskInfo(
                id=f"{serial or wwn}-{size}",
                path=stable_path,
                size_bytes=size,
                model=(dev.get("model") or "").strip(),
                serial=serial,
                wwn=wwn,
                major_minor=(dev.get("maj:min") or "").strip(),
                disk_sequence=disk_sequence,
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
            wwn="SIM-WWN-NVME-512",
            major_minor="259:0",
            disk_sequence=1,
            transport="nvme",
        ),
        DiskInfo(
            id="sim-ssd-256",
            path="/dev/disk/by-id/ulli-simulated-ssd",
            size_bytes=256 * 1024**3,
            model="ULI Simulated SSD 256G",
            serial="SIMSSD256",
            wwn="SIM-WWN-SSD-256",
            major_minor="8:0",
            disk_sequence=2,
            transport="sata",
        ),
    ]


def get_disks(*, simulate: bool | None = None) -> list[DiskInfo]:
    if simulate is None:
        simulate = os.environ.get("ULI_SIMULATE_DISK", "0") == "1"
    if simulate:
        return simulated_disks()
    return list_candidate_disks()
