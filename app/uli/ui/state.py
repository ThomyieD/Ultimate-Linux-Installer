from __future__ import annotations

from dataclasses import dataclass, field

from uli.core.plan import DistroSelection, PartitionSpec


@dataclass
class WizardState:
    language: str = "de"
    mode: str | None = None
    online: bool = False
    selected: list[DistroSelection] = field(default_factory=list)
    username: str = ""
    password: str = ""
    password_confirm: str = ""
    ssh_keys: list[str] = field(default_factory=list)
    theme: str = "uli-lenovo"
    equal_sizes: bool = True
    include_swap: bool = True
    include_data: bool = True
    disk_id: str | None = None
    disk_path: str | None = None
    disk_size_bytes: int = 0
    partitions: list[PartitionSpec] = field(default_factory=list)
    timezone: str = "Europe/Berlin"
    keyboard: str = "de"
