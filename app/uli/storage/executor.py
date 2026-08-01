from __future__ import annotations

from pathlib import Path

from uli.storage.layout import PartitionSpec


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
        # Real execution is only enabled in the live ISO with dry_run=False
        raise NotImplementedError(
            "Live partitioning executes only inside the bootable installer image"
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
            cmds.append(
                f"sgdisk -n {idx}:{start}M:{end}M -t {idx}:{typecode} "
                f"-c {idx}:{part.label or part.role} {disk_path}"
            )
            start = end
        for idx, part in enumerate(partitions, start=1):
            # Device node resolution is deferred to runtime (nvme uses pN suffix)
            node = f"{disk_path}{idx}"
            if part.filesystem == "fat32":
                cmds.append(f"mkfs.vfat -F32 -n {part.label or 'EFI'} {node}")
            elif part.filesystem == "ext4":
                cmds.append(f"mkfs.ext4 -L {part.label or part.role} {node}")
            elif part.filesystem == "swap":
                cmds.append(f"mkswap -L {part.label or 'swap'} {node}")
        return cmds


def write_commands(path: Path, commands: list[str]) -> None:
    path.write_text("\n".join(commands) + "\n", encoding="utf-8")
