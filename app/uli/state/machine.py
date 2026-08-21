"""Transactional installation state for resume-after-reboot orchestration."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

Status = Literal[
    "pending",
    "validated",
    "sources_verified",
    "partitioning",
    "filesystems",
    "installing",
    "verifying",
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
        default_factory=lambda: datetime.now(UTC).isoformat()
    )

    def touch(self) -> None:
        self.updated_at = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: str | Path) -> None:
        self.touch()
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
        payload = json.dumps(self.to_dict(), indent=2) + "\n"
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        temporary.replace(target)
        try:
            directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass


def load_state(path: str | Path) -> InstallState:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return InstallState(**data)


def default_state_path() -> Path:
    for candidate in (
        Path("/var/lib/uli/state.json"),
        Path("/run/uli/state.json"),
        Path.home() / ".cache" / "uli" / "state.json",
    ):
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            probe = candidate.parent / f".write-test-{os.getpid()}"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return candidate
        except OSError:
            continue
    return Path("state.json")
