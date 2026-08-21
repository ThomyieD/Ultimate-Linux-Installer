from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from uli.core.plan import DistroSelection, Filesystem, PartitionSpec


@dataclass
class DiskInfo:
    id: str
    path: str
    size_bytes: int
    model: str = ""
    serial: str = ""
    wwn: str = ""
    major_minor: str = ""
    disk_sequence: int = 0
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
DEFAULT_MINIMUM_ROOT_GIB = 20
ABSOLUTE_MINIMUM_ROOT_MIB = 4096
MINIMUM_SWAP_MIB = 256
MINIMUM_DATA_MIB = 1024

_SAFE_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_LABEL_LIMITS: dict[Filesystem, int] = {
    "fat32": 11,
    "ext4": 16,
    "btrfs": 255,
    "xfs": 12,
    "swap": 16,
}


def mib(bytes_value: int) -> int:
    if not isinstance(bytes_value, int) or isinstance(bytes_value, bool):
        raise TypeError("Disk size must be an integer number of bytes")
    if bytes_value <= 0:
        raise ValueError("Disk size must be greater than zero")
    return bytes_value // (1024 * 1024)


def align_down(value_mib: int) -> int:
    return max(0, (value_mib // ALIGN_MIB) * ALIGN_MIB)


def validate_partition_label(label: str, filesystem: Filesystem) -> None:
    """Validate a label accepted by both the filesystem and argv executor."""
    if not isinstance(label, str) or not label:
        raise ValueError("Partition label must not be empty")
    if not _SAFE_LABEL.fullmatch(label):
        raise ValueError(
            "Partition labels may contain only ASCII letters, digits, dot, underscore and dash"
        )
    limit = _LABEL_LIMITS[filesystem]
    if len(label.encode("ascii")) > limit:
        raise ValueError(f"{filesystem} labels must not exceed {limit} bytes")


def _compact_label(value: str, filesystem: Filesystem = "ext4") -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._").lower()
    if not slug:
        slug = "partition"
    limit = _LABEL_LIMITS[filesystem]
    if len(slug.encode("ascii")) <= limit:
        return slug
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:4]
    return f"{slug[: limit - len(digest) - 1]}-{digest}"


def _selection_key(distro: DistroSelection) -> str:
    return f"{distro.id}:{distro.variant}"


def _validate_selections(distros: list[DistroSelection]) -> None:
    if not distros:
        raise ValueError("At least one distribution is required")
    keys = [_selection_key(distro) for distro in distros]
    if len(keys) != len(set(keys)):
        raise ValueError("Each distribution and variant may occur only once")


def _minimum_root_mib(
    distro: DistroSelection,
    minimum_root_gib: dict[str, int] | None,
) -> int:
    minimums = minimum_root_gib or {}
    value = minimums.get(
        _selection_key(distro),
        minimums.get(distro.id, DEFAULT_MINIMUM_ROOT_GIB),
    )
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"Invalid minimum root size for {distro.id}")
    return value * 1024


def _optional_size(
    name: str,
    *,
    enabled: bool,
    configured_mib: int | None,
    default_mib: int,
    minimum_mib: int,
) -> int:
    if not enabled:
        if configured_mib not in (None, 0):
            raise ValueError(f"{name} size was provided although {name} is disabled")
        return 0
    value = default_mib if configured_mib is None else configured_mib
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} size must be a non-negative integer number of MiB")
    value = align_down(value)
    if 0 < value < minimum_mib:
        raise ValueError(f"{name} partition must be at least {minimum_mib} MiB")
    return value


def equal_root_layout(
    disk_size_bytes: int,
    distros: list[DistroSelection],
    *,
    include_swap: bool = True,
    include_data: bool = True,
    data_percent: int = 10,
    swap_size_mib: int | None = None,
    data_size_mib: int | None = None,
    minimum_root_gib: dict[str, int] | None = None,
    strict_minimums: bool = True,
) -> tuple[list[PartitionSpec], list[str]]:
    """Build a safe equal-size layout and return ``(partitions, warnings)``.

    ``swap_size_mib`` and ``data_size_mib`` are exact when supplied. Without an
    explicit data size, ``data_percent`` of the complete disk is reserved.
    Preview callers may opt into ``strict_minimums=False`` to render a soft-fit
    layout; an executable plan should always keep the default strict behavior.
    """
    _validate_selections(distros)
    total_mib = mib(disk_size_bytes)
    warnings: list[str] = []

    swap_mib = _optional_size(
        "swap",
        enabled=include_swap,
        configured_mib=swap_size_mib,
        default_mib=SWAP_MIB_DEFAULT,
        minimum_mib=MINIMUM_SWAP_MIB,
    )
    # Preserve the useful preview behavior on small disks, but never alter an
    # explicitly requested size.
    if include_swap and swap_size_mib is None and total_mib < 48 * 1024:
        swap_mib = 2048
        warnings.append("swap_reduced")

    wants_data = include_data and (len(distros) > 1 or data_size_mib is not None)
    if not include_data and data_size_mib not in (None, 0):
        raise ValueError("data size was provided although data is disabled")
    if not isinstance(data_percent, int) or isinstance(data_percent, bool):
        raise TypeError("data_percent must be an integer")
    if not 0 <= data_percent <= 90:
        raise ValueError("data_percent must be between 0 and 90")

    if wants_data and data_size_mib is None:
        data_mib = align_down(total_mib * data_percent // 100)
        if 0 < data_mib < MINIMUM_DATA_MIB:
            data_mib = 0
            warnings.append("data_disabled")
    else:
        data_mib = _optional_size(
            "data",
            enabled=wants_data,
            configured_mib=data_size_mib,
            default_mib=0,
            minimum_mib=MINIMUM_DATA_MIB,
        )

    fixed_mib = ESP_MIB + SAFETY_MIB + swap_mib + data_mib
    available_mib = total_mib - fixed_mib
    per_root_mib = align_down(available_mib // len(distros))
    if per_root_mib < ABSOLUTE_MINIMUM_ROOT_MIB:
        raise ValueError("Disk too small for the requested layout")

    for distro in distros:
        minimum_mib = _minimum_root_mib(distro, minimum_root_gib)
        if per_root_mib < minimum_mib:
            warnings.append(f"below_minimum:{distro.id}:{minimum_mib // 1024}")
            if strict_minimums:
                raise ValueError("Disk too small for selected distributions and minimum sizes")

    parts: list[PartitionSpec] = [
        PartitionSpec(role="esp", size_mib=ESP_MIB, filesystem="fat32", label="EFI")
    ]
    for distro in distros:
        parts.append(
            PartitionSpec(
                role="root",
                size_mib=per_root_mib,
                filesystem="ext4",
                distribution=_selection_key(distro),
                label=_compact_label(f"root-{distro.id}-{distro.variant}", filesystem="ext4"),
            )
        )
    if swap_mib:
        parts.append(PartitionSpec(role="swap", size_mib=swap_mib, filesystem="swap", label="swap"))
    if data_mib:
        parts.append(PartitionSpec(role="data", size_mib=data_mib, filesystem="ext4", label="data"))

    errors = validate_layout(parts, disk_size_bytes, minimum_root_gib=None)
    if not strict_minimums:
        errors = [error for error in errors if not error.startswith("Root partition ")]
    # A soft-fit preview is allowed below distribution-specific recommendations,
    # but never below the executor's absolute 10-GiB root safety floor.
    if errors:
        raise ValueError("; ".join(errors))
    return parts, warnings


def custom_root_layout(
    disk_size_bytes: int,
    root_sizes_mib: dict[str, int],
    distros: list[DistroSelection],
    *,
    include_swap: bool = True,
    include_data: bool = True,
    swap_size_mib: int | None = None,
    data_size_mib: int | None = None,
    minimum_root_gib: dict[str, int] | None = None,
    strict_minimums: bool = True,
) -> list[PartitionSpec]:
    """Build a layout from exact, per-distribution root sizes (slider output)."""
    _validate_selections(distros)
    total_mib = mib(disk_size_bytes)
    parts: list[PartitionSpec] = [
        PartitionSpec(role="esp", size_mib=ESP_MIB, filesystem="fat32", label="EFI")
    ]

    for distro in distros:
        key = _selection_key(distro)
        if key not in root_sizes_mib:
            raise ValueError(f"Missing root size for {key}")
        raw_size = root_sizes_mib[key]
        if not isinstance(raw_size, int) or isinstance(raw_size, bool) or raw_size <= 0:
            raise ValueError(f"Invalid root size for {key}")
        size_mib = align_down(raw_size)
        if size_mib < ABSOLUTE_MINIMUM_ROOT_MIB:
            raise ValueError(f"Root partition for {key} is below 4 GiB")
        minimum_mib = _minimum_root_mib(distro, minimum_root_gib)
        if strict_minimums and size_mib < minimum_mib:
            raise ValueError(
                f"Root partition for {key} is below its {minimum_mib // 1024} GiB minimum"
            )
        parts.append(
            PartitionSpec(
                role="root",
                size_mib=size_mib,
                filesystem="ext4",
                distribution=_selection_key(distro),
                label=_compact_label(f"root-{distro.id}-{distro.variant}"),
            )
        )

    swap_mib = _optional_size(
        "swap",
        enabled=include_swap,
        configured_mib=swap_size_mib,
        default_mib=SWAP_MIB_DEFAULT,
        minimum_mib=MINIMUM_SWAP_MIB,
    )
    if swap_mib:
        parts.append(PartitionSpec(role="swap", size_mib=swap_mib, filesystem="swap", label="swap"))

    remaining_mib = total_mib - SAFETY_MIB - sum(part.size_mib for part in parts)
    if remaining_mib < 0:
        raise ValueError("Selected partition sizes exceed disk capacity")

    if not include_data and data_size_mib not in (None, 0):
        raise ValueError("data size was provided although data is disabled")
    if include_data:
        if data_size_mib is None:
            data_mib = align_down(remaining_mib)
        else:
            data_mib = _optional_size(
                "data",
                enabled=True,
                configured_mib=data_size_mib,
                default_mib=0,
                minimum_mib=MINIMUM_DATA_MIB,
            )
        if data_mib > remaining_mib:
            raise ValueError("Selected partition sizes exceed disk capacity")
        if data_mib:
            if data_mib < MINIMUM_DATA_MIB:
                raise ValueError(f"data partition must be at least {MINIMUM_DATA_MIB} MiB")
            parts.append(
                PartitionSpec(role="data", size_mib=data_mib, filesystem="ext4", label="data")
            )

    errors = validate_layout(parts, disk_size_bytes, minimum_root_gib=minimum_root_gib)
    if not strict_minimums:
        errors = [error for error in errors if not error.startswith("Root partition ")]
    if errors:
        raise ValueError("; ".join(errors))
    return parts


def validate_layout(
    parts: list[PartitionSpec],
    disk_size_bytes: int,
    *,
    minimum_root_gib: dict[str, int] | None = None,
) -> list[str]:
    errors: list[str] = []
    try:
        usable_mib = mib(disk_size_bytes) - SAFETY_MIB
    except (TypeError, ValueError) as exc:
        return [str(exc)]

    total_mib = sum(part.size_mib for part in parts)
    if total_mib > usable_mib:
        errors.append("Partition sizes exceed disk capacity")

    esps = [part for part in parts if part.role == "esp"]
    if len(esps) != 1:
        errors.append("Exactly one EFI system partition is required")
    roots = [part for part in parts if part.role == "root"]
    if not roots:
        errors.append("At least one root partition is required")
    if len([part for part in parts if part.role == "swap"]) > 1:
        errors.append("At most one swap partition is supported")
    if len([part for part in parts if part.role == "data"]) > 1:
        errors.append("At most one data partition is supported")

    expected_filesystem = {
        "esp": "fat32",
        "root": "ext4",
        "swap": "swap",
        "data": "ext4",
    }
    seen_partuuids: set[str] = set()
    for part in parts:
        if part.filesystem != expected_filesystem.get(part.role):
            errors.append(f"Partition role {part.role} requires {expected_filesystem[part.role]}")
        if part.size_mib <= 0:
            errors.append(f"Partition {part.label or part.role} has an invalid size")
        label = part.label or part.role
        try:
            validate_partition_label(label, part.filesystem)
        except ValueError as exc:
            errors.append(str(exc))
        if not part.partuuid:
            errors.append(f"Partition {label} has no PARTUUID")
        elif part.partuuid in seen_partuuids:
            errors.append(f"Duplicate PARTUUID: {part.partuuid}")
        else:
            seen_partuuids.add(part.partuuid)

        if part.role == "root":
            minimum_gib = 10
            if minimum_root_gib is not None and part.distribution:
                minimum_gib = minimum_root_gib.get(
                    part.distribution,
                    minimum_root_gib.get(part.distribution.partition(":")[0], minimum_gib),
                )
            if part.size_mib < minimum_gib * 1024:
                errors.append(f"Root partition {label} is below {minimum_gib} GiB")
    return errors
