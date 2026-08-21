"""Safe argv-only command execution and mount lifecycle helpers.

The installer deliberately does not expose a shell command API.  Keeping every
operation as an argv tuple makes dry-runs useful, prevents quoting bugs, and
lets callers persist an exact audit trail.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

LogCallback = Callable[[str], None]


class RunnerError(RuntimeError):
    """Base class for command and cleanup failures."""


@dataclass(frozen=True)
class CommandRecord:
    """One effective command, including sudo/chroot prefixes when applicable."""

    argv: tuple[str, ...]
    chroot: str | None = None
    stdin_text: str | None = None
    sensitive_input: bool = False
    best_effort: bool = False

    @property
    def display(self) -> str:
        suffix = " <redacted stdin>" if self.sensitive_input else ""
        return shlex.join(self.argv) + suffix


@dataclass(frozen=True)
class CommandOutcome:
    record: CommandRecord
    returncode: int
    stdout: str = ""
    stderr: str = ""
    skipped: bool = False


class CommandExecutionError(RunnerError):
    def __init__(self, outcome: CommandOutcome) -> None:
        detail = (outcome.stderr or outcome.stdout).strip()
        if len(detail) > 4000:
            detail = detail[-4000:]
        message = f"Command failed with exit code {outcome.returncode}: {outcome.record.display}"
        if detail:
            message += f"\n{detail}"
        super().__init__(message)
        self.outcome = outcome


class CleanupError(RunnerError):
    """Raised when a mount cannot be removed, including by lazy unmount."""


class CommandRunner:
    """Execute commands without a shell, or only record them in dry-run mode."""

    def __init__(
        self,
        *,
        dry_run: bool = False,
        log: LogCallback | None = None,
        use_sudo: bool | None = None,
    ) -> None:
        self.dry_run = dry_run
        self.log = log or (lambda _message: None)
        self.use_sudo = (
            bool(hasattr(os, "geteuid") and os.geteuid() != 0) if use_sudo is None else use_sudo
        )
        self._commands: list[CommandRecord] = []

    @property
    def commands(self) -> list[CommandRecord]:
        return list(self._commands)

    def commands_since(self, offset: int) -> list[CommandRecord]:
        return list(self._commands[offset:])

    def require_tools(self, names: Iterable[str]) -> None:
        """Fail early for missing host tools; dry-runs remain host-independent."""
        if self.dry_run:
            return
        required = set(names)
        if self.use_sudo:
            required.add("sudo")
        missing = sorted(name for name in required if shutil.which(name) is None)
        if missing:
            raise RunnerError(f"Required command(s) missing: {', '.join(missing)}")

    def run(
        self,
        argv: Sequence[str],
        *,
        chroot: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        input_text: str | None = None,
        sensitive_input: bool = False,
        check: bool = True,
        ok_returncodes: Iterable[int] = (0,),
        best_effort: bool = False,
    ) -> CommandOutcome:
        if not argv:
            raise ValueError("argv must not be empty")
        raw = tuple(str(item) for item in argv)
        if any(not item or "\x00" in item for item in raw):
            raise ValueError("argv entries must be non-empty strings without NUL bytes")

        effective: list[str] = []
        root = str(chroot) if chroot is not None else None
        if root is not None:
            effective.extend(("chroot", "--", root))
            effective.extend(
                (
                    "env",
                    "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                )
            )
            if env:
                # Place the environment assignment *inside* chroot.  A sudo
                # policy may otherwise discard DEBIAN_FRONTEND/LC_ALL.
                effective.extend(f"{key}={value}" for key, value in env.items())
        effective.extend(raw)
        if self.use_sudo:
            effective[0:0] = ["sudo", "-n", "--"]

        record = CommandRecord(
            argv=tuple(effective),
            chroot=root,
            stdin_text=None if sensitive_input else input_text,
            sensitive_input=bool(input_text is not None and sensitive_input),
            best_effort=best_effort,
        )
        self._commands.append(record)
        prefix = "dry-run" if self.dry_run else "run"
        self.log(f"{prefix}: {record.display}")
        if self.dry_run:
            return CommandOutcome(record=record, returncode=0, skipped=True)

        process_env = os.environ.copy()
        if env:
            process_env.update({str(key): str(value) for key, value in env.items()})
        try:
            completed = subprocess.run(
                list(record.argv),
                check=False,
                capture_output=True,
                text=True,
                input=input_text,
                env=process_env,
            )
        except OSError as exc:
            outcome = CommandOutcome(record=record, returncode=127, stderr=str(exc))
            if check:
                raise CommandExecutionError(outcome) from exc
            return outcome

        outcome = CommandOutcome(
            record=record,
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )
        allowed = set(ok_returncodes)
        if check and completed.returncode not in allowed:
            raise CommandExecutionError(outcome)
        return outcome

    @contextmanager
    def mounted(
        self,
        source: str | Path,
        target: str | Path,
        *,
        filesystem: str | None = None,
        options: Sequence[str] = (),
    ) -> Iterator[Path]:
        """Mount a filesystem and always recursively unmount it in reverse flow."""
        mountpoint = _safe_mount_target(target)
        self.run(("install", "-d", "-m", "0755", str(mountpoint)))
        argv: list[str] = ["mount"]
        if filesystem:
            argv.extend(("--types", filesystem))
        argv.extend(str(option) for option in options)
        argv.extend(("--", str(source), str(mountpoint)))
        self.run(argv)
        try:
            yield mountpoint
        finally:
            self._unmount(mountpoint)

    @contextmanager
    def bind_mounted(
        self,
        source: str | Path,
        target: str | Path,
    ) -> Iterator[Path]:
        """Recursively bind mount a tree and make propagation private to cleanup."""
        mountpoint = _safe_mount_target(target)
        self.run(("install", "-d", "-m", "0755", str(mountpoint)))
        self.run(("mount", "--rbind", "--", str(source), str(mountpoint)))
        try:
            self.run(("mount", "--make-rslave", str(mountpoint)))
            yield mountpoint
        finally:
            self._unmount(mountpoint)

    @contextmanager
    def chroot_mounts(self, root: str | Path) -> Iterator[Path]:
        """Provide /dev, /proc, /sys and /run to a chroot and tear them down safely."""
        target_root = Path(root)
        with ExitStack() as stack:
            stack.enter_context(self.bind_mounted("/dev", target_root / "dev"))
            stack.enter_context(
                self.mounted(
                    "proc",
                    target_root / "proc",
                    filesystem="proc",
                    options=("--options", "nosuid,noexec,nodev"),
                )
            )
            stack.enter_context(self.bind_mounted("/sys", target_root / "sys"))
            stack.enter_context(self.bind_mounted("/run", target_root / "run"))
            yield target_root

    def _unmount(self, target: Path) -> None:
        first = self.run(
            ("umount", "--recursive", "--", str(target)),
            check=False,
            best_effort=True,
        )
        if first.returncode == 0:
            return
        lazy = self.run(
            ("umount", "--recursive", "--lazy", "--", str(target)),
            check=False,
            best_effort=True,
        )
        if lazy.returncode == 0:
            self.log(f"cleanup: lazy-unmounted {target}")
            return
        detail = (lazy.stderr or first.stderr or lazy.stdout or first.stdout).strip()
        message = f"Could not unmount {target}"
        if detail:
            message += f": {detail}"
        # Preserve an active installation exception; still make the cleanup issue visible.
        if sys.exc_info()[0] is not None:
            self.log(f"cleanup warning: {message}")
            return
        raise CleanupError(message)


def _safe_mount_target(path: str | Path) -> Path:
    target = Path(path)
    if not target.is_absolute():
        raise ValueError(f"Mount target must be absolute: {target}")
    normalized = Path(os.path.normpath(str(target)))
    # Restrict all temporary mounts to conventional scratch trees.  This also
    # catches a caller accidentally handing us /etc, /boot or a workspace root.
    allowed_roots = (Path("/mnt"), Path("/run"), Path("/tmp"))
    if not any(normalized != base and normalized.is_relative_to(base) for base in allowed_roots):
        raise ValueError(f"Unsafe mount target: {normalized}")
    return normalized
