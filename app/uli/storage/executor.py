from __future__ import annotations

import os
import subprocess
from pathlib import Path

from uli.storage.layout import PartitionSpec


def _part_node(disk_path: str, index: int) -> str:
    if any(x in disk_path for x in ("nvme", "mmcblk", "loop", "md")):
        return f"{disk_path}p{index}"
    return f"{disk_path}{index}"


class StorageGuard:
    """Central safety gate for destructive operations."""

    def __init__(self, *, dry_run: bool = True) -> None:
        self.dry_run = dry_run

    def apply_partition_table(
        self,
        disk_path: str,
        partitions: list[PartitionSpec],
        *,
        confirmed: bool,
    ) -> list[str]:
        if not confirmed:
            raise RuntimeError("Destructive storage operation was not confirmed")
        commands = self._build_commands(disk_path, partitions)
        if self.dry_run:
            return [f"# dry-run: {cmd}" for cmd in commands]
        self._execute(disk_path, commands)
        return commands

    def _execute(self, disk_path: str, commands: list[str]) -> None:
        for cmd in commands:
            argv = ["bash", "-lc", cmd]
            if hasattr(os, "geteuid") and os.geteuid() != 0:
                argv = ["sudo", "-n", *argv]
            result = subprocess.run(
                argv,
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"Command failed ({result.returncode}): {cmd}\n"
                    f"{result.stderr or result.stdout}"
                )
        settle = ["partprobe", disk_path]
        if hasattr(os, "geteuid") and os.geteuid() != 0:
            settle = ["sudo", "-n", *settle]
        subprocess.run(settle, check=False, capture_output=True)
        subprocess.run(
            ["sudo", "-n", "udevadm", "settle"]
            if hasattr(os, "geteuid") and os.geteuid() != 0
            else ["udevadm", "settle"],
            check=False,
            capture_output=True,
        )

    def _build_commands(self, disk_path: str, partitions: list[PartitionSpec]) -> list[str]:
        cmds = [
            f"wipefs -a {disk_path}",
            f"sgdisk --zap-all {disk_path}",
            f"sgdisk -og {disk_path}",
        ]
        start = 1  # MiB
        for idx, part in enumerate(partitions, start=1):
            end = start + part.size_mib
            typecode = {
                "esp": "EF00",
                "swap": "8200",
                "root": "8300",
                "data": "8300",
            }[part.role]
            label = (part.label or part.role).replace(" ", "-")
            cmds.append(
                f"sgdisk -n {idx}:{start}M:{end}M -t {idx}:{typecode} "
                f"-c {idx}:{label} {disk_path}"
            )
            start = end
        cmds.append(f"partprobe {disk_path} || true")
        cmds.append("udevadm settle || true")
        cmds.append("sleep 1")
        for idx, part in enumerate(partitions, start=1):
            node = _part_node(disk_path, idx)
            label = (part.label or part.role).replace(" ", "-")
            if part.filesystem == "fat32":
                cmds.append(f"mkfs.vfat -F32 -n {label[:11]} {node}")
            elif part.filesystem == "ext4":
                cmds.append(f"mkfs.ext4 -F -L {label} {node}")
            elif part.filesystem == "swap":
                cmds.append(f"mkswap -L {label} {node}")
        return cmds


def write_commands(path: Path, commands: list[str]) -> None:
    path.write_text("\n".join(commands) + "\n", encoding="utf-8")
