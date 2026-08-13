from __future__ import annotations

from dataclasses import dataclass

from uli.core.plan import DistroSelection, PartitionSpec


@dataclass
class DiskInfo:
    id: str
    path: str
    size_bytes: int
    model: str = ""
    serial: str = ""
    transport: str = ""
    is_installation_medium: bool = False
    is_removable: bool = False

    @property
    def size_gib(self) -> float:
        return self.size_bytes / (1024**3)


ESP_MIB = 1024
SWAP_MIB_DEFAULT = 8192
ALIGN_MIB = 1
SAFETY_MIB = 1024


def mib(bytes_value: int) -> int:
    return bytes_value // (1024 * 1024)


def align_down(value_mib: int) -> int:
    return max(ALIGN_MIB, (value_mib // ALIGN_MIB) * ALIGN_MIB)


def equal_root_layout(
    disk_size_bytes: int,
    distros: list[DistroSelection],
    *,
    include_swap: bool = True,
    include_data: bool = True,
    data_percent: int = 10,
    minimum_root_gib: dict[str, int] | None = None,
    strict_minimums: bool = False,
) -> tuple[list[PartitionSpec], list[str]]:
    """Build an even multiboot layout with ESP, roots, optional swap/data.

    Returns (partitions, warnings). When the disk is smaller than advertised
    minimums, non-strict mode fits what is possible and reports warnings.
    """
    if not distros:
        raise ValueError("At least one distribution is required")

    warnings: list[str] = []
    mins = minimum_root_gib or {}
    total_mib = mib(disk_size_bytes)
    if total_mib < ESP_MIB + SAFETY_MIB + 4096:
        raise ValueError("Disk too small for the requested layout")

    swap_mib = SWAP_MIB_DEFAULT if include_swap else 0
    # Shrink swap on small disks so a root can still fit
    if include_swap and total_mib < 48 * 1024:
        swap_mib = min(swap_mib, 2048)
        warnings.append("swap_reduced")

    reserved = ESP_MIB + SAFETY_MIB + swap_mib
    data_mib = 0
    if include_data and len(distros) > 1:
        data_mib = align_down(int(total_mib * (data_percent / 100)))
        # Cap data partition on small disks
        data_mib = min(data_mib, max(0, total_mib // 10))
        reserved += data_mib

    available = total_mib - reserved
    if available <= 0:
        if include_swap and swap_mib > 0:
            swap_mib = 0
            reserved = ESP_MIB + SAFETY_MIB + data_mib
            available = total_mib - reserved
            warnings.append("swap_disabled")
        if available <= 0:
            raise ValueError("Disk too small for the requested layout")

    per = align_down(available // len(distros))
    parts: list[PartitionSpec] = [
        PartitionSpec(role="esp", size_mib=ESP_MIB, filesystem="fat32", label="EFI")
    ]

    for distro in distros:
        min_mib = mins.get(distro.id, 20) * 1024
        if per < min_mib:
            warnings.append(f"below_minimum:{distro.id}:{min_mib // 1024}")
            if strict_minimums:
                raise ValueError(
                    "Disk too small for selected distributions and minimum sizes"
                )
            size = max(per, 4096)  # keep at least ~4 GiB root when fitting
        else:
            size = max(per, min_mib)
        parts.append(
            PartitionSpec(
                role="root",
                size_mib=size,
                filesystem="ext4",
                distribution=distro.id,
                label=f"root-{distro.id}-{distro.variant}",
            )
        )

    used = sum(p.size_mib for p in parts) + swap_mib
    overflow = used + data_mib - (total_mib - SAFETY_MIB)
    if overflow > 0:
        last = parts[-1]
        last.size_mib = align_down(last.size_mib - overflow)
        min_last = mins.get(distros[-1].id, 20) * 1024
        if last.size_mib < 4096:
            raise ValueError("Disk too small for selected distributions and minimum sizes")
        if last.size_mib < min_last:
            warnings.append(f"below_minimum:{distros[-1].id}:{min_last // 1024}")
            if strict_minimums:
                raise ValueError(
                    "Disk too small for selected distributions and minimum sizes"
                )

    if swap_mib > 0:
        parts.append(PartitionSpec(role="swap", size_mib=swap_mib, filesystem="swap", label="swap"))
    if data_mib > 0:
        remaining = (total_mib - SAFETY_MIB) - sum(p.size_mib for p in parts)
        if remaining >= 1024:
            parts.append(
                PartitionSpec(
                    role="data",
                    size_mib=align_down(max(remaining, 1024)),
                    filesystem="ext4",
                    label="data",
                )
            )
    return parts, warnings

def custom_root_layout(
    disk_size_bytes: int,
    root_sizes_mib: dict[str, int],
    distros: list[DistroSelection],
    *,
    include_swap: bool = True,
    include_data: bool = True,
) -> list[PartitionSpec]:
    """Build layout from explicit per-distro sizes (slider output)."""
    parts: list[PartitionSpec] = [
        PartitionSpec(role="esp", size_mib=ESP_MIB, filesystem="fat32", label="EFI")
    ]
    for distro in distros:
        key = f"{distro.id}:{distro.variant}"
        size = align_down(root_sizes_mib[key])
        parts.append(
            PartitionSpec(
                role="root",
                size_mib=size,
                filesystem="ext4",
                distribution=distro.id,
                label=f"root-{distro.id}-{distro.variant}",
            )
        )
    if include_swap:
        parts.append(
            PartitionSpec(role="swap", size_mib=SWAP_MIB_DEFAULT, filesystem="swap", label="swap")
        )
    used = sum(p.size_mib for p in parts)
    remaining = mib(disk_size_bytes) - SAFETY_MIB - used
    if include_data and remaining > 1024:
        parts.append(
            PartitionSpec(role="data", size_mib=align_down(remaining), filesystem="ext4", label="data")
        )
    elif remaining < 0:
        raise ValueError("Selected partition sizes exceed disk capacity")
    return parts


def validate_layout(parts: list[PartitionSpec], disk_size_bytes: int) -> list[str]:
    errors: list[str] = []
    total = sum(p.size_mib for p in parts)
    if total > mib(disk_size_bytes) - SAFETY_MIB:
        errors.append("Partition sizes exceed disk capacity")
    if not any(p.role == "esp" for p in parts):
        errors.append("EFI system partition is required")
    roots = [p for p in parts if p.role == "root"]
    if not roots:
        errors.append("At least one root partition is required")
    for p in roots:
        if p.size_mib < 10 * 1024:
            errors.append(f"Root partition {p.label} is below 10 GiB")
    return errors
