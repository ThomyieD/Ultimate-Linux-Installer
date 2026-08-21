from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from uuid import UUID, uuid4

import yaml

Mode = Literal["simple", "multiboot", "add", "remove"]
PartitionRole = Literal["esp", "root", "swap", "data"]
Filesystem = Literal["fat32", "ext4", "btrfs", "xfs", "swap"]

_SAFE_DEVICE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]*$")
_SAFE_PARTITION_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_FILESYSTEM_LABEL_LIMITS: dict[str, int] = {
    "fat32": 11,
    "ext4": 16,
    "btrfs": 255,
    "xfs": 12,
    "swap": 16,
}


@dataclass
class LocaleConfig:
    language: str = "de_DE.UTF-8"
    timezone: str = "Europe/Berlin"
    keyboard: str = "de"


@dataclass
class DiskTarget:
    id: str
    path: str
    size_bytes: int
    table: str = "gpt"
    wipe: bool = True
    model: str = ""
    serial: str = ""
    wwn: str = ""
    major_minor: str = ""
    disk_sequence: int = 0

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Disk target id must not be empty")
        if not isinstance(self.path, str) or not self.path:
            raise ValueError("Disk target path must not be empty")
        path = PurePosixPath(self.path)
        if (
            "\x00" in self.path
            or any(char.isspace() for char in self.path)
            or not path.is_absolute()
            or len(path.parts) < 3
            or path.parts[:2] != ("/", "dev")
            or any(
                part in {".", ".."} or not _SAFE_DEVICE_COMPONENT.fullmatch(part)
                for part in path.parts[2:]
            )
        ):
            raise ValueError("Disk target must be a safe absolute path below /dev")
        if not isinstance(self.size_bytes, int) or isinstance(self.size_bytes, bool):
            raise TypeError("Disk target size must be an integer")
        if self.size_bytes <= 0:
            raise ValueError("Disk target size must be greater than zero")
        if self.table != "gpt":
            raise ValueError("Only GPT partition tables are supported")
        for field_name in ("model", "serial", "wwn", "major_minor"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or any(char in value for char in ("\x00", "\n", "\r")):
                raise ValueError(f"Disk target {field_name} must be a single-line string")
        if self.major_minor and not re.fullmatch(r"[0-9]+:[0-9]+", self.major_minor):
            raise ValueError("Disk target major_minor must use MAJOR:MINOR format")
        if not isinstance(self.disk_sequence, int) or isinstance(self.disk_sequence, bool):
            raise TypeError("Disk target disk_sequence must be an integer")
        if self.disk_sequence < 0:
            raise ValueError("Disk target disk_sequence must not be negative")


@dataclass
class PartitionSpec:
    role: PartitionRole
    size_mib: int
    filesystem: Filesystem = "ext4"
    distribution: str | None = None
    label: str | None = None
    partuuid: str | None = None
    uuid: str | None = None

    def __post_init__(self) -> None:
        if self.role not in {"esp", "root", "swap", "data"}:
            raise ValueError(f"Unsupported partition role: {self.role}")
        if self.filesystem not in {"fat32", "ext4", "btrfs", "xfs", "swap"}:
            raise ValueError(f"Unsupported filesystem: {self.filesystem}")
        if not isinstance(self.size_mib, int) or isinstance(self.size_mib, bool):
            raise TypeError("Partition size must be an integer number of MiB")
        if self.size_mib <= 0:
            raise ValueError("Partition size must be greater than zero")
        if self.label is not None and not self.label:
            raise ValueError("Partition label must not be empty")
        if self.label is not None:
            if not _SAFE_PARTITION_LABEL.fullmatch(self.label):
                raise ValueError(
                    "Partition labels may contain only ASCII letters, digits, dot, "
                    "underscore and dash"
                )
            limit = _FILESYSTEM_LABEL_LIMITS[self.filesystem]
            if len(self.label.encode("ascii")) > limit:
                raise ValueError(f"{self.filesystem} labels must not exceed {limit} bytes")

        try:
            self.partuuid = str(UUID(self.partuuid)) if self.partuuid else str(uuid4())
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("PARTUUID must be a valid GPT partition UUID") from exc


@dataclass
class DistroSelection:
    id: str
    variant: str
    display_name: str
    release: str | None = None
    desktop: str | None = None
    hostname: str | None = None


@dataclass
class UserConfig:
    username: str
    password_hash: str | None = None
    ssh_keys: list[str] = field(default_factory=list)
    sudo: bool = True
    disable_password_auth: bool = False
    install_ssh_server: bool = True


@dataclass
class BootloaderConfig:
    kind: str = "grub"
    theme: str = "uli-lenovo"
    timeout_seconds: int = 5
    efi_directory: str = "UltimateInstaller"
    default_entry: str | None = None


@dataclass
class NetworkConfig:
    method: str = "dhcp"
    ssid: str | None = None
    persist: bool = True


@dataclass
class InstallationPlan:
    mode: Mode
    disk: DiskTarget
    partitions: list[PartitionSpec]
    distributions: list[DistroSelection]
    user: UserConfig
    bootloader: BootloaderConfig = field(default_factory=BootloaderConfig)
    locale: LocaleConfig = field(default_factory=LocaleConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    plan_id: str = field(default_factory=lambda: uuid4().hex[:12])
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    confirmed: bool = False

    def __post_init__(self) -> None:
        if self.mode not in {"simple", "multiboot", "add", "remove"}:
            raise ValueError(f"Unsupported installation mode: {self.mode}")
        if self.mode in {"add", "remove"} and self.disk.wipe:
            raise ValueError(f"Mode {self.mode!r} must never use a wipe plan")

        partuuids: set[str] = set()
        for partition in self.partitions:
            # PartitionSpec normally assigns this in __post_init__. Keeping this
            # fallback makes plans built by older callers safe as well.
            if not partition.partuuid:
                partition.partuuid = str(uuid4())
            normalized = str(UUID(partition.partuuid))
            if normalized in partuuids:
                raise ValueError(f"Duplicate PARTUUID in installation plan: {normalized}")
            partition.partuuid = normalized
            partuuids.add(normalized)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_yaml(), encoding="utf-8")

    def require_confirmed(self) -> None:
        if not self.confirmed:
            raise RuntimeError("Destructive storage operation was not confirmed")


def load_plan(path: str | Path) -> InstallationPlan:
    raw = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    return plan_from_dict(data)


def plan_from_dict(data: dict[str, Any]) -> InstallationPlan:
    return InstallationPlan(
        plan_id=data.get("plan_id", uuid4().hex[:12]),
        created_at=data.get("created_at", datetime.now(UTC).isoformat()),
        mode=data["mode"],
        locale=LocaleConfig(**data.get("locale", {})),
        disk=DiskTarget(**data["disk"]),
        partitions=[PartitionSpec(**p) for p in data.get("partitions", [])],
        distributions=[DistroSelection(**d) for d in data.get("distributions", [])],
        user=UserConfig(**data["user"]),
        bootloader=BootloaderConfig(**data.get("bootloader", {})),
        network=NetworkConfig(**data.get("network", {})),
        confirmed=bool(data.get("confirmed", False)),
    )
