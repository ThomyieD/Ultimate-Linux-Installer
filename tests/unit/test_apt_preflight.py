from __future__ import annotations

from pathlib import Path

import pytest
from uli.core.plan import (
    BootloaderConfig,
    DiskTarget,
    DistroSelection,
    InstallationPlan,
    LocaleConfig,
    PartitionSpec,
    UserConfig,
)
from uli.install.apt_preflight import AptPreflightError, run_apt_preflight
from uli.install.runner import CommandExecutionError, CommandOutcome, CommandRecord, CommandRunner


def _plan(*variants: str) -> InstallationPlan:
    if not variants:
        variants = ("server",)
    distributions = [
        DistroSelection(
            "debian",
            variant,
            f"Debian {variant}",
            release="trixie",
            hostname=f"debian-{variant}",
        )
        for variant in variants
    ]
    partitions = [
        PartitionSpec(
            role="esp",
            size_mib=1024,
            filesystem="fat32",
            label="EFI",
            partuuid="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            uuid="12AB-34CD",
        )
    ]
    for index, selection in enumerate(distributions, start=1):
        partitions.append(
            PartitionSpec(
                role="root",
                size_mib=20 * 1024,
                filesystem="ext4",
                distribution=f"{selection.id}:{selection.variant}",
                label=f"deb-{selection.variant}",
                partuuid=f"bbbbbbbb-bbbb-4bbb-8bbb-{index:012d}",
                uuid=f"{index:08d}-1111-4111-8111-111111111111",
            )
        )
    return InstallationPlan(
        mode="simple" if len(distributions) == 1 else "multiboot",
        disk=DiskTarget(id="disk0", path="/dev/sda", size_bytes=80 * 1024**3),
        partitions=partitions,
        distributions=distributions,
        user=UserConfig(username="alice", password_hash="$6$rounds=5000$salt$hash", sudo=True),
        locale=LocaleConfig(language="de_DE.UTF-8", timezone="Europe/Berlin", keyboard="de"),
        bootloader=BootloaderConfig(theme="uli-lenovo"),
        confirmed=True,
    )


def _patch_sources(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    keyring = tmp_path / "debian-archive-keyring.gpg"
    keyring.write_bytes(b"keyring")
    monkeypatch.setattr(
        "uli.install.apt_preflight.distro_sources_list",
        lambda _selection: (
            f"deb [signed-by={keyring}] https://deb.debian.org/debian trixie main\n",
            str(keyring),
        ),
    )


def test_dry_run_preflight_does_not_invoke_apt(tmp_path: Path) -> None:
    calls: list[tuple[str, ...]] = []

    class RecordingRunner(CommandRunner):
        def run(self, argv, **kwargs):  # type: ignore[no-untyped-def]
            calls.append(tuple(str(item) for item in argv))
            return super().run(argv, **kwargs)

    runner = RecordingRunner(dry_run=False, use_sudo=False)
    run_apt_preflight(_plan(), tmp_path, dry_run=True, runner=runner)
    assert calls == []


def test_real_mode_refuses_dry_run_runner(tmp_path: Path) -> None:
    with pytest.raises(AptPreflightError, match="dry-run command runner"):
        run_apt_preflight(
            _plan(),
            tmp_path,
            dry_run=False,
            runner=CommandRunner(dry_run=True, use_sudo=False),
        )


def test_real_preflight_unions_variants_and_pins_amd64(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_sources(monkeypatch, tmp_path)
    seen: list[tuple[str, ...]] = []

    class FakeRunner(CommandRunner):
        def run(self, argv, **kwargs):  # type: ignore[no-untyped-def]
            command = tuple(str(item) for item in argv)
            seen.append(command)
            assert all("trusted=yes" not in part for part in command)
            assert "--allow-unauthenticated" not in command
            assert any(part.startswith("-oDir=") for part in command)
            assert "-oAPT::Architecture=amd64" in command
            assert "-oAPT::Architectures=amd64" in command
            record = CommandRecord(argv=command)
            return CommandOutcome(record=record, returncode=0)

    # server before desktop: still one APT root, package union includes desktop metapackage
    run_apt_preflight(
        _plan("server", "desktop"),
        tmp_path,
        dry_run=False,
        runner=FakeRunner(dry_run=False),
    )
    assert len(seen) == 2
    assert "update" in seen[0]
    assert "install" in seen[1] and "-s" in seen[1]
    assert "tasksel" in seen[1]
    assert "task-gnome-desktop" in seen[1]
    assert "-oAPT::Architecture=amd64" in seen[0]
    assert "-oAPT::Architecture=amd64" in seen[1]
    assert not (tmp_path / "apt-preflight").exists()


def test_preflight_failure_is_fatal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_sources(monkeypatch, tmp_path)

    class FailingRunner(CommandRunner):
        def run(self, argv, **kwargs):  # type: ignore[no-untyped-def]
            command = tuple(str(item) for item in argv)
            record = CommandRecord(argv=command)
            outcome = CommandOutcome(record=record, returncode=100, stderr="boom")
            raise CommandExecutionError(outcome)

    with pytest.raises(AptPreflightError, match="before wipe"):
        run_apt_preflight(
            _plan(),
            tmp_path,
            dry_run=False,
            runner=FailingRunner(dry_run=False),
        )
