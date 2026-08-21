from __future__ import annotations

import json
import os
import stat
from collections.abc import Sequence
from types import SimpleNamespace

import pytest
from uli.core.plan import DistroSelection, PartitionSpec
from uli.storage import executor
from uli.storage.executor import (
    CommandResult,
    StorageExecutionError,
    StorageGuard,
    StorageSafetyError,
    ValidatedTarget,
    assert_target_binding,
    validate_target,
)
from uli.storage.layout import equal_root_layout

GIB = 1024**3


def _parts() -> list[PartitionSpec]:
    parts, _warnings = equal_root_layout(
        64 * GIB,
        [DistroSelection("ubuntu", "desktop", "Ubuntu Desktop")],
        include_data=False,
    )
    return parts


def _validated(path: str, size_bytes: int = 64 * GIB) -> ValidatedTarget:
    return ValidatedTarget(
        path=path,
        canonical_path=path,
        size_bytes=size_bytes,
        serial="SERIAL",
        model="Mock Disk",
        wwn="mock-wwn",
        major_minor="8:0",
        disk_sequence=9,
        device_number=(8, 0),
        device_paths=(path,),
    )


class RecordingRunner:
    def __init__(self, parts: list[PartitionSpec], *, fail_command: str | None = None) -> None:
        self.parts = parts
        self.fail_command = fail_command
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv: Sequence[str]) -> CommandResult:
        call = tuple(argv)
        self.calls.append(call)
        if self.fail_command and call[0] == self.fail_command:
            return CommandResult(2, stderr="mock failure")
        if call[0] == "blkid":
            node = call[-1]
            marker = "-part" if "-part" in node else "p" if node[-2:-1] == "p" else ""
            index = int(node.rsplit(marker, 1)[-1]) if marker else int(node[-1])
            return CommandResult(
                0,
                stdout=(f"UUID=filesystem-{index}\nPARTUUID={self.parts[index - 1].partuuid}\n"),
            )
        return CommandResult(0)


def test_dry_run_uses_plus_size_gpt_geometry_and_preassigned_guids() -> None:
    parts = _parts()
    commands = StorageGuard(dry_run=True).apply_partition_table(
        "/dev/nvme0n1",
        parts,
        confirmed=True,
        mode="simple",
        wipe=True,
        expected_size_bytes=64 * GIB,
    )

    partition_commands = [command for command in commands if "--new=" in command]
    assert len(partition_commands) == len(parts)
    assert all(":0:+" in command for command in partition_commands)
    assert all("--partition-guid=" in command for command in partition_commands)
    assert not any("bash" in command or "-lc" in command for command in commands)


@pytest.mark.parametrize("mode", ["add", "remove"])
def test_wipe_executor_rejects_add_and_remove_modes(mode: str) -> None:
    with pytest.raises(StorageSafetyError, match="wipe is forbidden"):
        StorageGuard(dry_run=True).apply_partition_table(
            "/dev/sda",
            _parts(),
            confirmed=True,
            mode=mode,  # type: ignore[arg-type]
            wipe=True,
        )


def test_wipe_executor_requires_mode_wipe_and_confirmation_guards() -> None:
    guard = StorageGuard(dry_run=True)
    with pytest.raises(StorageSafetyError, match="not confirmed"):
        guard.apply_partition_table("/dev/sda", _parts(), confirmed=False, mode="simple", wipe=True)
    with pytest.raises(StorageSafetyError, match="wipe=True"):
        guard.apply_partition_table("/dev/sda", _parts(), confirmed=True, mode="simple", wipe=False)


@pytest.mark.parametrize(
    "path",
    ["/dev/sda;reboot", "/dev/sda $(reboot)", "/tmp/disk", "/dev/../etc/passwd"],
)
def test_disk_path_rejects_shell_and_traversal_payloads(path: str) -> None:
    with pytest.raises(StorageSafetyError):
        StorageGuard(dry_run=True).apply_partition_table(
            path,
            _parts(),
            confirmed=True,
            mode="simple",
            wipe=True,
        )


def test_mutated_unsafe_label_is_rejected_before_command_execution() -> None:
    parts = _parts()
    parts[1].label = "root;reboot"
    runner = RecordingRunner(parts)
    guard = StorageGuard(dry_run=False, runner=runner, privilege_prefix=())

    with pytest.raises(StorageSafetyError, match="ASCII letters"):
        guard.apply_partition_table(
            "/dev/sda",
            parts,
            confirmed=True,
            mode="simple",
            wipe=True,
        )
    assert runner.calls == []


def test_executor_passes_only_argv_and_records_blkid_identifiers() -> None:
    parts = _parts()
    runner = RecordingRunner(parts)
    guard = StorageGuard(
        dry_run=False,
        runner=runner,
        privilege_prefix=(),
        target_validator=lambda path, **_kwargs: _validated(path),
    )

    guard.apply_partition_table(
        "/dev/disk/by-id/mock-disk",
        parts,
        confirmed=True,
        mode="simple",
        wipe=True,
        expected_size_bytes=64 * GIB,
        expected_serial="SERIAL",
    )

    assert runner.calls[0] == ("wipefs", "--all", "/dev/disk/by-id/mock-disk")
    assert all(call[0] not in {"bash", "sh"} for call in runner.calls)
    assert any(call[-1].endswith("-part1") for call in runner.calls if call[0] == "blkid")
    assert [part.uuid for part in parts] == [
        f"filesystem-{index}" for index in range(1, len(parts) + 1)
    ]


def test_executor_stops_on_first_failed_argv_command() -> None:
    parts = _parts()
    runner = RecordingRunner(parts, fail_command="wipefs")
    guard = StorageGuard(
        dry_run=False,
        runner=runner,
        privilege_prefix=(),
        target_validator=lambda path, **_kwargs: _validated(path),
    )

    with pytest.raises(StorageExecutionError, match="mock failure"):
        guard.apply_partition_table(
            "/dev/sda",
            parts,
            confirmed=True,
            mode="simple",
            wipe=True,
        )
    assert runner.calls == [("wipefs", "--all", "/dev/sda")]


def _lsblk_runner(
    *,
    mounted: bool = False,
    size_bytes: int = 64 * GIB,
    serial_value: str = "SERIAL",
    model_value: str = "Mock Disk",
    wwn_value: str = "0xmockwwn",
    major_minor_value: str = "8:0",
) -> RecordingRunner:
    root = {
        "path": "/dev/sda",
        "type": "disk",
        "size": size_bytes,
        "serial": serial_value,
        "model": model_value,
        "wwn": wwn_value,
        "maj:min": major_minor_value,
        "mountpoints": [None],
        "children": [
            {
                "path": "/dev/sda1",
                "type": "part",
                "size": 1024**3,
                "serial": None,
                "mountpoints": ["/mnt/data"] if mounted else [None],
            }
        ],
    }

    class LsblkRunner(RecordingRunner):
        def __init__(self) -> None:
            super().__init__([])

        def __call__(self, argv: Sequence[str]) -> CommandResult:
            self.calls.append(tuple(argv))
            return CommandResult(0, stdout=json.dumps({"blockdevices": [root]}))

    return LsblkRunner()


def _mock_block_stat(_path: str) -> SimpleNamespace:
    return SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=os.makedev(8, 0))


@pytest.fixture(autouse=True)
def _stable_disk_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    realpath = os.path.realpath
    monkeypatch.setattr(
        executor,
        "find_stable_disk_path",
        lambda _path: "/dev/disk/by-id/mock-SERIAL",
    )
    monkeypatch.setattr(
        executor.os.path,
        "realpath",
        lambda path: "/dev/sda"
        if str(path) == "/dev/disk/by-id/mock-SERIAL"
        else realpath(path),
    )
    monkeypatch.setattr(executor, "read_disk_sequence", lambda _path: 9)


def test_validate_target_rejects_mounted_children(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(executor.os, "stat", _mock_block_stat)
    with pytest.raises(StorageSafetyError, match="mounted"):
        validate_target(
            "/dev/sda",
            runner=_lsblk_runner(mounted=True),
            installation_media_paths=(),
            active_swap_paths=(),
        )


def test_validate_target_rejects_active_swap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(executor.os, "stat", _mock_block_stat)
    with pytest.raises(StorageSafetyError, match="active swap"):
        validate_target(
            "/dev/sda",
            expected_serial="SERIAL",
            runner=_lsblk_runner(),
            installation_media_paths=(),
            active_swap_paths=("/dev/sda1",),
        )


def test_validate_target_rejects_installation_medium(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(executor.os, "stat", _mock_block_stat)
    with pytest.raises(StorageSafetyError, match="installation medium"):
        validate_target(
            "/dev/sda",
            expected_serial="SERIAL",
            runner=_lsblk_runner(),
            installation_media_paths=("/dev/sda1",),
            active_swap_paths=(),
        )


def test_validate_target_checks_expected_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(executor.os, "stat", _mock_block_stat)
    with pytest.raises(StorageSafetyError, match="size changed"):
        validate_target(
            "/dev/sda",
            expected_size_bytes=32 * GIB,
            runner=_lsblk_runner(),
            installation_media_paths=(),
            active_swap_paths=(),
        )


def test_validate_target_rejects_disk_without_stable_hardware_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(executor.os, "stat", _mock_block_stat)
    with pytest.raises(StorageSafetyError, match="no stable serial or WWN"):
        validate_target(
            "/dev/sda",
            expected_major_minor="8:0",
            runner=_lsblk_runner(serial_value="", wwn_value=""),
            installation_media_paths=(),
            active_swap_paths=(),
        )
    with pytest.raises(StorageSafetyError, match="serial changed"):
        validate_target(
            "/dev/sda",
            expected_serial="OTHER",
            runner=_lsblk_runner(),
            installation_media_paths=(),
            active_swap_paths=(),
        )
    with pytest.raises(StorageSafetyError, match="WWN changed"):
        validate_target(
            "/dev/sda",
            expected_wwn="other-wwn",
            runner=_lsblk_runner(),
            installation_media_paths=(),
            active_swap_paths=(),
        )


def test_validate_target_accepts_complete_identity_and_rejects_node_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(executor.os, "stat", _mock_block_stat)
    target = validate_target(
        "/dev/sda",
        expected_size_bytes=64 * GIB,
        expected_serial="SERIAL",
        expected_model="Mock Disk",
        expected_wwn="0xmockwwn",
        expected_major_minor="8:0",
        runner=_lsblk_runner(),
        installation_media_paths=(),
        active_swap_paths=(),
    )
    assert target.device_number == (8, 0)
    assert target.path == "/dev/disk/by-id/mock-SERIAL"

    calls = 0

    def changing_stat(_path: str) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        minor = 0 if calls == 1 else 16
        return SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=os.makedev(8, minor))

    monkeypatch.setattr(executor.os, "stat", changing_stat)
    with pytest.raises(StorageSafetyError, match="device node changed"):
        validate_target(
            "/dev/sda",
            expected_serial="SERIAL",
            runner=_lsblk_runner(),
            installation_media_paths=(),
            active_swap_paths=(),
        )


def test_stable_target_binding_rejects_retargeted_by_id_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = ValidatedTarget(
        path="/dev/disk/by-id/mock-SERIAL",
        canonical_path="/dev/sda",
        size_bytes=64 * GIB,
        serial="SERIAL",
        model="Mock Disk",
        wwn="0xmockwwn",
        major_minor="8:0",
        disk_sequence=9,
        device_number=(8, 0),
        device_paths=("/dev/sda",),
    )
    monkeypatch.setattr(executor.os.path, "realpath", lambda _path: "/dev/sdb")
    monkeypatch.setattr(
        executor.os,
        "stat",
        lambda _path: SimpleNamespace(
            st_mode=stat.S_IFBLK,
            st_rdev=os.makedev(8, 16),
        ),
    )

    with pytest.raises(StorageSafetyError, match="binding changed"):
        assert_target_binding(target)


def test_validate_target_rejects_stat_lsblk_identity_disagreement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        executor.os,
        "stat",
        lambda _path: SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=os.makedev(8, 16)),
    )
    with pytest.raises(StorageSafetyError, match="disagrees between device node and lsblk"):
        validate_target(
            "/dev/sda",
            expected_serial="SERIAL",
            expected_major_minor="8:0",
            runner=_lsblk_runner(major_minor_value="8:0"),
            installation_media_paths=(),
            active_swap_paths=(),
        )


def test_validate_target_reinspects_stable_alias_after_reused_dev_t(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ReusedDeviceRunner:
        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []

        def __call__(self, argv: Sequence[str]) -> CommandResult:
            self.calls.append(tuple(argv))
            serial = "OLD" if len(self.calls) == 1 else "NEW"
            root = {
                "path": "/dev/sda",
                "type": "disk",
                "size": 64 * GIB,
                "model": "Mock Disk",
                "serial": serial,
                "wwn": f"0x{serial.lower()}",
                "maj:min": "8:0",
                "mountpoints": [None],
            }
            return CommandResult(0, stdout=json.dumps({"blockdevices": [root]}))

    runner = ReusedDeviceRunner()
    monkeypatch.setattr(executor.os, "stat", _mock_block_stat)

    with pytest.raises(StorageSafetyError, match="identity changed"):
        validate_target(
            "/dev/sda",
            expected_size_bytes=64 * GIB,
            expected_serial="OLD",
            expected_model="Mock Disk",
            expected_wwn="0xold",
            expected_major_minor="8:0",
            runner=runner,
            installation_media_paths=(),
            active_swap_paths=(),
        )

    assert [call[-1] for call in runner.calls] == [
        "/dev/sda",
        "/dev/disk/by-id/mock-SERIAL",
    ]


def test_executor_rejects_reused_dev_t_before_first_destructive_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parts = _parts()

    class ReusedDeviceRunner(RecordingRunner):
        def __init__(self) -> None:
            super().__init__(parts)
            self.inspections = 0

        def __call__(self, argv: Sequence[str]) -> CommandResult:
            call = tuple(argv)
            self.calls.append(call)
            if call[0] != "lsblk":
                return super().__call__(argv)
            self.inspections += 1
            serial = "OLD" if self.inspections == 1 else "NEW"
            root = {
                "path": "/dev/sda",
                "type": "disk",
                "size": 64 * GIB,
                "model": "Mock Disk",
                "serial": serial,
                "wwn": f"0x{serial.lower()}",
                "maj:min": "8:0",
                "mountpoints": [None],
            }
            return CommandResult(0, stdout=json.dumps({"blockdevices": [root]}))

    runner = ReusedDeviceRunner()
    monkeypatch.setattr(executor, "_default_runner", runner)
    monkeypatch.setattr(executor.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(executor.os, "stat", _mock_block_stat)

    guard = StorageGuard(dry_run=False, privilege_prefix=())
    with pytest.raises(StorageSafetyError, match="identity changed"):
        guard.apply_partition_table(
            "/dev/sda",
            parts,
            confirmed=True,
            mode="simple",
            wipe=True,
            expected_size_bytes=64 * GIB,
            expected_serial="OLD",
            expected_model="Mock Disk",
            expected_wwn="0xold",
            expected_major_minor="8:0",
        )

    assert runner.inspections == 2
    assert all(call[0] == "lsblk" for call in runner.calls)
