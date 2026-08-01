"""Transactional installation state for resume-after-reboot orchestration."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

Status = Literal[
    "pending",
    "partitioning",
    "downloading",
    "installing",
    "bootloader",
    "completed",
    "failed",
]


@dataclass
class InstallState:
    plan_id: str
    status: Status = "pending"
    completed: list[str] = field(default_factory=list)
    current: str | None = None
    remaining: list[str] = field(default_factory=list)
    error: str | None = None
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: str | Path) -> None:
        self.touch()
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")


def load_state(path: str | Path) -> InstallState:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return InstallState(**data)


def default_state_path() -> Path:
    for candidate in (
        Path("/var/lib/uli/state.json"),
        Path("/run/uli/state.json"),
        Path.home() / ".cache" / "uli" / "state.json",
    ):
        if candidate.parent.exists() or candidate == Path.home() / ".cache" / "uli" / "state.json":
            candidate.parent.mkdir(parents=True, exist_ok=True)
            return candidate
    return Path("state.json")
