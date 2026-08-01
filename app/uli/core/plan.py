from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import yaml

Mode = Literal["simple", "multiboot", "add", "remove"]
PartitionRole = Literal["esp", "root", "swap", "data"]


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


@dataclass
class PartitionSpec:
    role: PartitionRole
    size_mib: int
    filesystem: str = "ext4"
    distribution: str | None = None
    label: str | None = None
    partuuid: str | None = None
    uuid: str | None = None


@dataclass
class DistroSelection:
    id: str
    variant: str
    display_name: str
    release: str | None = None
    desktop: str | None = None


@dataclass
class UserConfig:
    username: str
    password_hash: str | None = None
    ssh_keys: list[str] = field(default_factory=list)
    sudo: bool = True
    disable_password_auth: bool = False


@dataclass
class BootloaderConfig:
    kind: str = "grub"
    theme: str = "uli-lenovo"
    timeout_seconds: int = 5
    efi_directory: str = "UltimateInstaller"


@dataclass
class NetworkConfig:
    method: str = "dhcp"
    ssid: str | None = None


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
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    confirmed: bool = False

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
        created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
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
