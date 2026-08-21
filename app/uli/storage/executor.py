from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import stat
import subprocess
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol
from uuid import UUID

from uli.core.plan import InstallationPlan, Mode, PartitionSpec
from uli.storage.disks import (
    detect_installation_medium_paths,
    find_stable_disk_path,
    get_disk_sequence,
    read_disk_sequence,
)
from uli.storage.layout import validate_layout, validate_partition_label


class StorageSafetyError(RuntimeError):
    """Raised before a destructive operation when a safety invariant fails."""


class StorageExecutionError(RuntimeError):
    """Raised when a storage command fails or returns inconsistent metadata."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class CommandRunner(Protocol):
    def __call__(self, argv: Sequence[str]) -> CommandResult | subprocess.CompletedProcess[str]: ...


CommandPhase = Literal["wipe", "partition", "settle", "format", "identify"]


@dataclass(frozen=True)
class StorageCommand:
    argv: tuple[str, ...]
    phase: CommandPhase
    partition_index: int | None = None

    def render(self) -> str:
        return shlex.join(self.argv)


@dataclass(frozen=True)
class ValidatedTarget:
    path: str
    canonical_path: str
    size_bytes: int
    serial: str
    device_paths: tuple[str, ...]
    model: str
    wwn: str
    major_minor: str
    disk_sequence: int
    device_number: tuple[int, int]


TargetValidator = Callable[..., ValidatedTarget]

_DEVICE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]*$")


def validate_disk_path(disk_path: str) -> None:
    """Accept absolute /dev paths without traversal or control characters."""
    if not isinstance(disk_path, str) or not disk_path:
        raise StorageSafetyError("Target disk path must not be empty")
    if "\x00" in disk_path or any(char.isspace() for char in disk_path):
        raise StorageSafetyError("Target disk path contains unsafe characters")
    path = PurePosixPath(disk_path)
    if not path.is_absolute() or len(path.parts) < 3 or path.parts[:2] != ("/", "dev"):
        raise StorageSafetyError("Target disk must be an absolute path below /dev")
    if any(part in {".", ".."} or not _DEVICE_COMPONENT.fullmatch(part) for part in path.parts[2:]):
        raise StorageSafetyError("Target disk path contains an invalid component")


def _default_runner(
    argv: Sequence[str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        check=False,
        capture_output=True,
        text=True,
    )


def _coerce_result(
    result: CommandResult | subprocess.CompletedProcess[str],
) -> CommandResult:
    return CommandResult(
        returncode=int(result.returncode),
        stdout=result.stdout or "",
        stderr=result.stderr or "",
    )


def _call_runner(runner: CommandRunner, argv: Sequence[str]) -> CommandResult:
    if not argv or any(not isinstance(arg, str) or "\x00" in arg for arg in argv):
        raise StorageExecutionError("Refusing to execute an invalid argv vector")
    try:
        return _coerce_result(runner(tuple(argv)))
    except FileNotFoundError as exc:
        raise StorageExecutionError(f"Required storage tool is unavailable: {argv[0]}") from exc


def _call_host_command(argv: Sequence[str], *, pass_fds: Sequence[int]) -> CommandResult:
    if not argv or any(not isinstance(arg, str) or "\x00" in arg for arg in argv):
        raise StorageExecutionError("Refusing to execute an invalid argv vector")
    try:
        return _coerce_result(
            subprocess.run(
                list(argv),
                check=False,
                capture_output=True,
                text=True,
                pass_fds=tuple(pass_fds),
            )
        )
    except FileNotFoundError as exc:
        raise StorageExecutionError(f"Required storage tool is unavailable: {argv[0]}") from exc


def _walk_lsblk(entry: dict[str, object]) -> list[dict[str, object]]:
    devices = [entry]
    for child in entry.get("children") or []:  # type: ignore[union-attr]
        if isinstance(child, dict):
            devices.extend(_walk_lsblk(child))
    return devices


def _mountpoints(entry: dict[str, object]) -> list[str]:
    raw = entry.get("mountpoints", entry.get("mountpoint"))
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw] if raw else []
    if isinstance(raw, list):
        return [str(value) for value in raw if value]
    return [str(raw)]


def _active_swap_paths() -> set[str]:
    try:
        lines = Path("/proc/swaps").read_text(encoding="utf-8").splitlines()[1:]
    except OSError:
        return set()
    return {line.split()[0] for line in lines if line.split()}


def _canonical_device(path: str) -> str:
    return os.path.realpath(path) if path.startswith("/dev/") else path


def assert_target_binding(target: ValidatedTarget) -> None:
    """Fail closed if a verified by-id alias no longer names the same device."""
    if not target.path.startswith("/dev/disk/by-id/"):
        raise StorageSafetyError("Destructive target is not bound through /dev/disk/by-id")
    try:
        alias_stat = os.stat(target.path)
        current_canonical = _canonical_device(target.path)
        canonical_stat = os.stat(current_canonical)
    except OSError as exc:
        raise StorageSafetyError("Stable target disk alias disappeared during execution") from exc
    if not stat.S_ISBLK(alias_stat.st_mode) or not stat.S_ISBLK(canonical_stat.st_mode):
        raise StorageSafetyError("Stable target disk alias no longer resolves to a block device")
    current_number = (os.major(alias_stat.st_rdev), os.minor(alias_stat.st_rdev))
    if (
        current_number != target.device_number
        or canonical_stat.st_rdev != alias_stat.st_rdev
        or current_canonical != target.canonical_path
    ):
        raise StorageSafetyError("Stable target disk binding changed during execution")


def assert_target_identity(target: ValidatedTarget, runner: CommandRunner) -> None:
    """Re-inspect a bound alias and reject reused kernel device identities."""
    assert_target_binding(target)
    result = _call_runner(
        runner,
        (
            "lsblk",
            "--json",
            "--bytes",
            "--tree",
            "--output",
            "PATH,TYPE,SIZE,MODEL,SERIAL,WWN,MAJ:MIN,MOUNTPOINTS",
            target.path,
        ),
    )
    if result.returncode != 0:
        raise StorageSafetyError(
            f"Unable to re-inspect target disk {target.path}: {result.stderr or result.stdout}"
        )
    try:
        payload = json.loads(result.stdout)
        roots = payload["blockdevices"]
        root = roots[0]
    except (IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise StorageSafetyError(f"lsblk returned invalid data for {target.path}") from exc
    if not isinstance(root, dict) or root.get("type") != "disk":
        raise StorageSafetyError(f"Target is not a whole disk: {target.path}")

    root_path = str(root.get("path") or "")
    try:
        size_bytes = int(root.get("size") or 0)
        lsblk_number = tuple(int(value) for value in str(root.get("maj:min") or "").split(":", 1))
    except (TypeError, ValueError) as exc:
        raise StorageSafetyError("lsblk returned an invalid target disk identity") from exc
    actual = (
        size_bytes,
        str(root.get("model") or "").strip(),
        str(root.get("serial") or "").strip(),
        str(root.get("wwn") or "").strip(),
        str(root.get("maj:min") or "").strip(),
    )
    expected = (
        target.size_bytes,
        target.model,
        target.serial,
        target.wwn,
        target.major_minor,
    )
    if (
        not root_path.startswith("/dev/")
        or _canonical_device(root_path) != target.canonical_path
        or actual != expected
        or lsblk_number != target.device_number
        or read_disk_sequence(target.path) != target.disk_sequence
    ):
        raise StorageSafetyError("Stable target disk identity changed during execution")

    # Close the lsblk race by checking the alias binding again after inspection.
    assert_target_binding(target)


def assert_open_target_identity(
    target: ValidatedTarget,
    fd: int,
    runner: CommandRunner,
) -> None:
    """Verify that an open FD and the live alias still name the selected disk."""
    try:
        opened_stat = os.fstat(fd)
        opened_sequence = get_disk_sequence(fd)
    except OSError as exc:
        raise StorageSafetyError("Unable to verify open target disk identity") from exc
    if (
        not stat.S_ISBLK(opened_stat.st_mode)
        or (os.major(opened_stat.st_rdev), os.minor(opened_stat.st_rdev))
        != target.device_number
        or opened_sequence != target.disk_sequence
    ):
        raise StorageSafetyError("Open target disk identity changed during execution")
    assert_target_identity(target, runner)
    try:
        if os.fstat(fd).st_rdev != opened_stat.st_rdev or get_disk_sequence(fd) != opened_sequence:
            raise StorageSafetyError("Open target disk identity changed during execution")
    except OSError as exc:
        raise StorageSafetyError("Unable to verify open target disk identity") from exc


def validate_target(
    disk_path: str,
    *,
    expected_size_bytes: int | None = None,
    expected_serial: str | None = None,
    expected_model: str | None = None,
    expected_wwn: str | None = None,
    expected_major_minor: str | None = None,
    expected_disk_sequence: int | None = None,
    runner: CommandRunner | None = None,
    installation_media_paths: Collection[str] | None = None,
    active_swap_paths: Collection[str] | None = None,
) -> ValidatedTarget:
    """Validate a live wipe target without unmounting or modifying anything."""
    validate_disk_path(disk_path)
    try:
        device_stat = os.stat(disk_path)
    except OSError as exc:
        raise StorageSafetyError(f"Target disk does not exist: {disk_path}") from exc
    if not stat.S_ISBLK(device_stat.st_mode):
        raise StorageSafetyError(f"Target is not a block device: {disk_path}")
    actual_disk_sequence = read_disk_sequence(disk_path)
    if actual_disk_sequence <= 0:
        raise StorageSafetyError("Target disk has no positive kernel disk sequence")
    if expected_disk_sequence is not None and actual_disk_sequence != expected_disk_sequence:
        raise StorageSafetyError(
            "Target disk sequence changed "
            f"(expected {expected_disk_sequence}, found {actual_disk_sequence})"
        )

    command_runner = runner or _default_runner
    result = _call_runner(
        command_runner,
        (
            "lsblk",
            "--json",
            "--bytes",
            "--tree",
            "--output",
            "PATH,TYPE,SIZE,MODEL,SERIAL,WWN,MAJ:MIN,MOUNTPOINTS",
            disk_path,
        ),
    )
    if result.returncode != 0:
        raise StorageSafetyError(
            f"Unable to inspect target disk {disk_path}: {result.stderr or result.stdout}"
        )
    try:
        payload = json.loads(result.stdout)
        roots = payload["blockdevices"]
        root = roots[0]
    except (IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise StorageSafetyError(f"lsblk returned invalid data for {disk_path}") from exc
    if not isinstance(root, dict) or root.get("type") != "disk":
        raise StorageSafetyError(f"Target is not a whole disk: {disk_path}")

    entries = _walk_lsblk(root)
    mounted = [
        f"{entry.get('path')}: {mountpoint}"
        for entry in entries
        for mountpoint in _mountpoints(entry)
    ]
    if mounted:
        raise StorageSafetyError(
            "Target disk or a child partition is mounted; refusing to unmount it: "
            + ", ".join(mounted)
        )

    device_paths = {
        str(entry["path"])
        for entry in entries
        if isinstance(entry.get("path"), str) and entry.get("path")
    }
    canonical_paths = {_canonical_device(path) for path in device_paths}
    canonical_paths.add(_canonical_device(disk_path))

    swaps = active_swap_paths if active_swap_paths is not None else _active_swap_paths()
    active_on_target = sorted(
        path for path in swaps if _canonical_device(str(path)) in canonical_paths
    )
    if active_on_target:
        raise StorageSafetyError(
            "Target disk has active swap; refusing to disable it: " + ", ".join(active_on_target)
        )

    media_paths = (
        installation_media_paths
        if installation_media_paths is not None
        else detect_installation_medium_paths()
    )
    media_on_target = sorted(
        str(path)
        for path in media_paths
        if str(path).startswith("/dev/") and _canonical_device(str(path)) in canonical_paths
    )
    if media_on_target:
        raise StorageSafetyError(
            "Target disk is the installation medium: " + ", ".join(media_on_target)
        )

    try:
        actual_size = int(root.get("size") or 0)
    except (TypeError, ValueError) as exc:
        raise StorageSafetyError("Unable to determine target disk size") from exc
    actual_serial = str(root.get("serial") or "").strip()
    actual_model = str(root.get("model") or "").strip()
    actual_wwn = str(root.get("wwn") or "").strip()
    actual_major_minor = str(root.get("maj:min") or "").strip()
    actual_root_path = str(root.get("path") or "")
    if actual_size <= 0:
        raise StorageSafetyError("Unable to determine target disk size")
    if expected_size_bytes is not None and actual_size != expected_size_bytes:
        raise StorageSafetyError(
            f"Target disk size changed (expected {expected_size_bytes}, found {actual_size})"
        )
    if not expected_serial and not expected_wwn:
        raise StorageSafetyError(
            "Target disk has no stable serial or WWN identity; real installation is unsupported"
        )
    if expected_serial and actual_serial != expected_serial.strip():
        raise StorageSafetyError(
            f"Target disk serial changed (expected {expected_serial!r}, found {actual_serial!r})"
        )
    if expected_model and actual_model != expected_model.strip():
        raise StorageSafetyError(
            f"Target disk model changed (expected {expected_model!r}, found {actual_model!r})"
        )
    if expected_wwn and actual_wwn != expected_wwn.strip():
        raise StorageSafetyError(
            f"Target disk WWN changed (expected {expected_wwn!r}, found {actual_wwn!r})"
        )
    if expected_major_minor and actual_major_minor != expected_major_minor.strip():
        raise StorageSafetyError(
            "Target disk kernel identity changed "
            f"(expected {expected_major_minor!r}, found {actual_major_minor!r})"
        )
    try:
        lsblk_major, lsblk_minor = (int(value) for value in actual_major_minor.split(":", 1))
    except (TypeError, ValueError) as exc:
        raise StorageSafetyError("lsblk returned an invalid target disk MAJ:MIN identity") from exc
    stat_device_number = (os.major(device_stat.st_rdev), os.minor(device_stat.st_rdev))
    if (lsblk_major, lsblk_minor) != stat_device_number:
        raise StorageSafetyError(
            "Target disk identity disagrees between device node and lsblk "
            f"({stat_device_number[0]}:{stat_device_number[1]} vs {actual_major_minor})"
        )

    # Re-stat after lsblk so a retargeted /dev symlink cannot silently pass the
    # identity snapshot that immediately precedes wipefs.
    final_canonical_path = _canonical_device(disk_path)
    validate_disk_path(final_canonical_path)
    if (
        not actual_root_path.startswith("/dev/")
        or _canonical_device(actual_root_path) != final_canonical_path
    ):
        raise StorageSafetyError("lsblk returned a different target disk root path")
    try:
        final_stat = os.stat(final_canonical_path)
        final_alias_stat = os.stat(disk_path)
    except OSError as exc:
        raise StorageSafetyError(f"Target disk disappeared: {disk_path}") from exc
    if (
        final_stat.st_rdev != device_stat.st_rdev
        or final_alias_stat.st_rdev != device_stat.st_rdev
    ):
        raise StorageSafetyError("Target disk device node changed during final validation")

    stable_path = find_stable_disk_path(final_canonical_path)
    if stable_path is None:
        raise StorageSafetyError(
            "Target disk has no stable /dev/disk/by-id alias; real installation is unsupported"
        )
    try:
        stable_stat = os.stat(stable_path)
    except OSError as exc:
        raise StorageSafetyError("Stable target disk alias disappeared during validation") from exc
    if stable_stat.st_rdev != final_stat.st_rdev:
        raise StorageSafetyError("Stable target disk alias does not match the validated device")

    device_paths.add(stable_path)
    target = ValidatedTarget(
        path=stable_path,
        canonical_path=final_canonical_path,
        size_bytes=actual_size,
        serial=actual_serial,
        model=actual_model,
        wwn=actual_wwn,
        major_minor=actual_major_minor,
        disk_sequence=actual_disk_sequence,
        device_number=(os.major(final_stat.st_rdev), os.minor(final_stat.st_rdev)),
        device_paths=tuple(sorted(device_paths)),
    )
    # st_rdev alone is insufficient: Linux can reuse a removed disk's device
    # number.  Inspect the selected alias itself before returning the target.
    assert_target_identity(target, command_runner)
    return target


def _part_node(disk_path: str, index: int) -> str:
    if disk_path.startswith(("/dev/disk/by-id/", "/dev/disk/by-path/")):
        return f"{disk_path}-part{index}"
    name = PurePosixPath(disk_path).name
    if name.startswith(("nvme", "mmcblk", "loop", "md")) or name[-1:].isdigit():
        return f"{disk_path}p{index}"
    return f"{disk_path}{index}"


class StorageGuard:
    """Central, injectable safety gate for whole-disk destructive operations."""

    def __init__(
        self,
        *,
        dry_run: bool = True,
        runner: CommandRunner | None = None,
        target_validator: TargetValidator | None = None,
        installation_media_paths: Collection[str] | None = None,
        privilege_prefix: Sequence[str] | None = None,
    ) -> None:
        self.dry_run = dry_run
        self._uses_host_runner = runner is None
        self._runner = runner or _default_runner
        self._target_validator = target_validator or validate_target
        self._installation_media_paths = installation_media_paths
        if privilege_prefix is None:
            privilege_prefix = (
                ("sudo", "-n") if hasattr(os, "geteuid") and os.geteuid() != 0 else ()
            )
        self._privilege_prefix = tuple(privilege_prefix)

    def apply_plan(self, plan: InstallationPlan) -> list[str]:
        """Apply the storage section of a fully populated installation plan."""
        return self.apply_partition_table(
            plan.disk.path,
            plan.partitions,
            confirmed=plan.confirmed,
            mode=plan.mode,
            wipe=plan.disk.wipe,
            expected_size_bytes=plan.disk.size_bytes,
            expected_serial=plan.disk.serial or None,
            expected_model=plan.disk.model or None,
            expected_wwn=plan.disk.wwn or None,
            expected_major_minor=plan.disk.major_minor or None,
            expected_disk_sequence=plan.disk.disk_sequence or None,
        )

    def apply_partition_table(
        self,
        disk_path: str,
        partitions: list[PartitionSpec],
        *,
        confirmed: bool,
        mode: Mode,
        wipe: bool,
        expected_size_bytes: int | None = None,
        expected_serial: str | None = None,
        expected_model: str | None = None,
        expected_wwn: str | None = None,
        expected_major_minor: str | None = None,
        expected_disk_sequence: int | None = None,
    ) -> list[str]:
        if not confirmed:
            raise StorageSafetyError("Destructive storage operation was not confirmed")
        if mode not in {"simple", "multiboot"}:
            raise StorageSafetyError(f"Whole-disk wipe is forbidden in {mode!r} mode")
        if wipe is not True:
            raise StorageSafetyError("Whole-disk executor requires an explicit wipe=True plan")
        validate_disk_path(disk_path)
        self._validate_partitions(partitions)
        if expected_size_bytes is not None:
            errors = validate_layout(partitions, expected_size_bytes)
            if errors:
                raise StorageSafetyError("Invalid storage layout: " + "; ".join(errors))

        commands = self._build_commands(disk_path, partitions)
        rendered = [command.render() for command in commands]
        if self.dry_run:
            return [f"# dry-run: {command}" for command in rendered]
        executed_commands = self._execute(
            disk_path,
            partitions,
            commands,
            expected_size_bytes=expected_size_bytes,
            expected_serial=expected_serial,
            expected_model=expected_model,
            expected_wwn=expected_wwn,
            expected_major_minor=expected_major_minor,
            expected_disk_sequence=expected_disk_sequence,
        )
        return [command.render() for command in executed_commands]

    def _validate_partitions(self, partitions: list[PartitionSpec]) -> None:
        if not partitions:
            raise StorageSafetyError("A wipe plan must contain partitions")
        if len([partition for partition in partitions if partition.role == "esp"]) != 1:
            raise StorageSafetyError("A wipe plan requires exactly one EFI partition")
        if not any(partition.role == "root" for partition in partitions):
            raise StorageSafetyError("A wipe plan requires at least one root partition")

        expected_filesystem = {
            "esp": "fat32",
            "root": "ext4",
            "swap": "swap",
            "data": "ext4",
        }
        seen_partuuids: set[str] = set()
        for partition in partitions:
            if partition.filesystem != expected_filesystem[partition.role]:
                raise StorageSafetyError(
                    f"Partition role {partition.role} requires {expected_filesystem[partition.role]}"
                )
            if partition.size_mib <= 0:
                raise StorageSafetyError("Partition sizes must be greater than zero")
            label = partition.label or partition.role
            try:
                validate_partition_label(label, partition.filesystem)
                normalized_partuuid = str(UUID(partition.partuuid or ""))
            except ValueError as exc:
                raise StorageSafetyError(str(exc)) from exc
            if normalized_partuuid in seen_partuuids:
                raise StorageSafetyError(f"Duplicate PARTUUID: {normalized_partuuid}")
            partition.partuuid = normalized_partuuid
            seen_partuuids.add(normalized_partuuid)

    def _execute(
        self,
        disk_path: str,
        partitions: list[PartitionSpec],
        commands: list[StorageCommand],
        *,
        expected_size_bytes: int | None,
        expected_serial: str | None,
        expected_model: str | None,
        expected_wwn: str | None,
        expected_major_minor: str | None,
        expected_disk_sequence: int | None,
    ) -> list[StorageCommand]:
        if self._uses_host_runner:
            required = {command.argv[0] for command in commands}
            required.update(self._privilege_prefix[:1])
            missing = sorted(name for name in required if name and shutil.which(name) is None)
            if missing:
                raise StorageSafetyError(
                    "Required storage tool(s) unavailable before wipe: " + ", ".join(missing)
                )
        # This is deliberately the final operation before the first wipefs call.
        target = self._target_validator(
            disk_path,
            expected_size_bytes=expected_size_bytes,
            expected_serial=expected_serial,
            expected_model=expected_model,
            expected_wwn=expected_wwn,
            expected_major_minor=expected_major_minor,
            expected_disk_sequence=expected_disk_sequence,
            runner=self._runner,
            installation_media_paths=self._installation_media_paths,
        )
        errors = validate_layout(partitions, target.size_bytes)
        if errors:
            raise StorageSafetyError("Invalid storage layout: " + "; ".join(errors))

        # Keep every command anchored to the verified udev identity alias.  A
        # reusable kernel node such as /dev/sda is never used after validation.
        commands = self._build_commands(target.path, partitions)

        if self._uses_host_runner:
            self._execute_fd_bound(target, partitions, commands)
            return commands

        for command in commands:
            result = _call_runner(self._runner, (*self._privilege_prefix, *command.argv))
            if result.returncode != 0:
                raise StorageExecutionError(
                    f"Command failed ({result.returncode}): {command.render()}\n"
                    f"{result.stderr or result.stdout}"
                )
            if command.phase == "identify":
                assert command.partition_index is not None
                self._record_identifiers(
                    partitions[command.partition_index - 1],
                    command,
                    result.stdout,
                )
        return commands

    def _execute_fd_bound(
        self,
        target: ValidatedTarget,
        partitions: list[PartitionSpec],
        commands: list[StorageCommand],
    ) -> None:
        """Execute against inherited FDs so udev aliases cannot retarget commands."""
        flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
        try:
            disk_fd = os.open(target.path, flags)
        except OSError as exc:
            raise StorageSafetyError("Unable to open verified target disk for execution") from exc

        partition_fds: dict[int, int] = {}
        try:
            assert_open_target_identity(target, disk_fd, self._runner)
            for command in commands:
                assert_open_target_identity(target, disk_fd, self._runner)
                argv = [
                    f"/proc/self/fd/{disk_fd}" if arg == target.path else arg
                    for arg in command.argv
                ]
                pass_fds = [disk_fd]

                if command.phase in {"format", "identify"}:
                    assert command.partition_index is not None
                    partition_fd = partition_fds.get(command.partition_index)
                    if partition_fd is None:
                        partition = partitions[command.partition_index - 1]
                        partition_fd = self._open_partition_fd(partition, target.disk_sequence)
                        partition_fds[command.partition_index] = partition_fd
                    pass_fds.append(partition_fd)
                    partition_node = _part_node(target.path, command.partition_index)
                    argv = [
                        f"/proc/self/fd/{partition_fd}" if arg == partition_node else arg
                        for arg in argv
                    ]

                result = _call_host_command(
                    (*self._privilege_prefix, *argv),
                    pass_fds=pass_fds,
                )
                if result.returncode != 0:
                    raise StorageExecutionError(
                        f"Command failed ({result.returncode}): {command.render()}\n"
                        f"{result.stderr or result.stdout}"
                    )
                if command.phase == "identify":
                    assert command.partition_index is not None
                    self._record_identifiers(
                        partitions[command.partition_index - 1],
                        command,
                        result.stdout,
                    )
                    os.close(partition_fds.pop(command.partition_index))
        finally:
            for partition_fd in partition_fds.values():
                os.close(partition_fd)
            os.close(disk_fd)

    def _open_partition_fd(
        self,
        partition: PartitionSpec,
        expected_disk_sequence: int,
    ) -> int:
        assert partition.partuuid is not None
        path = f"/dev/disk/by-partuuid/{partition.partuuid}"
        flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
        fd: int | None = None
        try:
            fd = os.open(path, flags)
            partition_stat = os.fstat(fd)
            partition_sequence = get_disk_sequence(fd)
        except OSError as exc:
            if fd is not None:
                os.close(fd)
            raise StorageSafetyError(
                f"Unable to bind created partition {partition.partuuid}"
            ) from exc
        if (
            not stat.S_ISBLK(partition_stat.st_mode)
            or partition_sequence != expected_disk_sequence
        ):
            os.close(fd)
            raise StorageSafetyError(
                f"Created partition {partition.partuuid} is not bound to the target disk"
            )
        return fd

    def _record_identifiers(
        self,
        partition: PartitionSpec,
        command: StorageCommand,
        output: str,
    ) -> None:
        values = {
            key: value
            for line in output.splitlines()
            if "=" in line
            for key, value in [line.split("=", 1)]
        }
        filesystem_uuid = values.get("UUID")
        reported_partuuid = values.get("PARTUUID") or values.get("PART_ENTRY_UUID")
        if not filesystem_uuid or not reported_partuuid:
            raise StorageExecutionError(
                f"blkid did not return UUID and PARTUUID: {command.render()}"
            )
        try:
            normalized = str(UUID(reported_partuuid))
        except ValueError as exc:
            raise StorageExecutionError(
                f"blkid returned an invalid PARTUUID for {command.render()}"
            ) from exc
        if normalized != partition.partuuid:
            raise StorageExecutionError(
                "Created partition PARTUUID does not match the installation plan "
                f"(expected {partition.partuuid}, found {normalized})"
            )
        partition.partuuid = normalized
        partition.uuid = filesystem_uuid

    def _build_commands(
        self,
        disk_path: str,
        partitions: list[PartitionSpec],
    ) -> list[StorageCommand]:
        commands = [
            StorageCommand(("wipefs", "--all", disk_path), "wipe"),
            StorageCommand(("sgdisk", "--zap-all", disk_path), "wipe"),
            StorageCommand(("sgdisk", "--clear", disk_path), "partition"),
        ]
        typecodes = {"esp": "EF00", "swap": "8200", "root": "8300", "data": "8300"}
        for index, partition in enumerate(partitions, start=1):
            label = partition.label or partition.role
            commands.append(
                StorageCommand(
                    (
                        "sgdisk",
                        f"--new={index}:0:+{partition.size_mib}M",
                        f"--typecode={index}:{typecodes[partition.role]}",
                        f"--change-name={index}:{label}",
                        f"--partition-guid={index}:{partition.partuuid}",
                        disk_path,
                    ),
                    "partition",
                    index,
                )
            )
        commands.extend(
            [
                StorageCommand(("sgdisk", "--verify", disk_path), "partition"),
                StorageCommand(("partprobe", disk_path), "settle"),
                StorageCommand(("udevadm", "settle"), "settle"),
            ]
        )
        for index, partition in enumerate(partitions, start=1):
            node = _part_node(disk_path, index)
            label = partition.label or partition.role
            if partition.filesystem == "fat32":
                argv = ("mkfs.vfat", "-F", "32", "-n", label, node)
            elif partition.filesystem == "ext4":
                argv = ("mkfs.ext4", "-F", "-L", label, node)
            elif partition.filesystem == "swap":
                argv = ("mkswap", "-L", label, node)
            else:  # The safety validator currently rejects all other filesystems.
                raise StorageSafetyError(f"Unsupported filesystem: {partition.filesystem}")
            commands.append(StorageCommand(argv, "format", index))
            commands.append(
                StorageCommand(
                    ("blkid", "--output", "export", node),
                    "identify",
                    index,
                )
            )
        return commands


def write_commands(path: Path, commands: list[str]) -> None:
    path.write_text("\n".join(commands) + "\n", encoding="utf-8")
