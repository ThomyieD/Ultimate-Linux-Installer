from __future__ import annotations

from pathlib import Path

import pytest
from uli.bootloader.grub import (
    GrubInstallError,
    UnsupportedSecureBootError,
    _find_chef_boot_number,
    install_chef_grub,
    preflight_chef_grub_build,
    render_grub_cfg,
    secure_boot_enabled,
    validate_uefi_environment,
)
from uli.core.plan import (
    BootloaderConfig,
    DiskTarget,
    DistroSelection,
    InstallationPlan,
    LocaleConfig,
    PartitionSpec,
    UserConfig,
)
from uli.install.provision import (
    Provisioner,
    ProvisioningError,
    UnsupportedDistributionError,
    keyboard_configuration,
    provision_plan,
    validate_host_timezone,
)
from uli.install.runner import CommandRunner


def _plan() -> InstallationPlan:
    return InstallationPlan(
        mode="multiboot",
        disk=DiskTarget(
            id="disk0",
            path="/dev/nvme0n1",
            size_bytes=128 * 1024**3,
        ),
        partitions=[
            PartitionSpec(
                role="esp",
                size_mib=1024,
                filesystem="fat32",
                label="EFI",
                partuuid="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                uuid="12AB-34CD",
            ),
            PartitionSpec(
                role="root",
                size_mib=40 * 1024,
                filesystem="ext4",
                distribution="debian",
                label="deb-desktop",
                partuuid="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                uuid="11111111-1111-4111-8111-111111111111",
            ),
            PartitionSpec(
                role="root",
                size_mib=40 * 1024,
                filesystem="ext4",
                distribution="ubuntu",
                label="ubu-server",
                partuuid="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
                uuid="22222222-2222-4222-8222-222222222222",
            ),
            PartitionSpec(
                role="swap",
                size_mib=2048,
                filesystem="swap",
                label="swap",
                partuuid="dddddddd-dddd-4ddd-8ddd-dddddddddddd",
                uuid="33333333-3333-4333-8333-333333333333",
            ),
        ],
        distributions=[
            DistroSelection(
                "debian",
                "desktop",
                "Debian 13 Desktop",
                release="trixie",
                hostname="workstation",
            ),
            DistroSelection(
                "ubuntu",
                "server",
                "Ubuntu 26.04 Server",
                release="26.04 LTS",
                hostname="homeserver",
            ),
        ],
        user=UserConfig(
            username="alice",
            password_hash="$6$rounds=10000$salt$hash",
            ssh_keys=["ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest alice@example"],
            sudo=True,
            disable_password_auth=True,
        ),
        locale=LocaleConfig(
            language="de_DE.UTF-8",
            timezone="Europe/Berlin",
            keyboard="de",
        ),
        bootloader=BootloaderConfig(
            kind="grub",
            theme="uli-lenovo",
            timeout_seconds=7,
            efi_directory="UltimateInstaller",
            default_entry="ubuntu:server",
        ),
        confirmed=True,
    )


def _records_writing(result: object, destination: str):
    commands = result.commands
    return [record for record in commands if record.argv[-2:] == ("tee", destination)]


def test_provision_dry_run_plans_both_signed_official_repositories() -> None:
    plan = _plan()
    events: list[tuple[str, int, str]] = []
    result = provision_plan(
        plan,
        dry_run=True,
        mount_root="/mnt/uli-test",
        progress=lambda phase, percent, message: events.append((phase, percent, message)),
    )

    assert result.completed == ["debian:desktop", "ubuntu:server"]
    assert result.dry_run is True
    bootstrap = [record.argv for record in result.commands if "debootstrap" in record.argv]
    assert len(bootstrap) == 2
    assert any(
        "trixie" in command and "https://deb.debian.org/debian" in command for command in bootstrap
    )
    assert any(
        "resolute" in command and "https://archive.ubuntu.com/ubuntu" in command
        for command in bootstrap
    )
    assert all(any(arg.startswith("--keyring=") for arg in command) for command in bootstrap)
    assert events[-1][:2] == ("done", 100)

    apt_sources = _records_writing(result, "/etc/apt/sources.list")
    assert len(apt_sources) == 2
    assert all(
        "signed-by=/usr/share/keyrings/" in (record.stdin_text or "") for record in apt_sources
    )
    assert all("https://" in (record.stdin_text or "") for record in apt_sources)


def test_provision_plan_contains_machine_configuration_and_no_plain_secret() -> None:
    plan = _plan()
    result = provision_plan(plan, dry_run=True, mount_root="/mnt/uli-test")

    fstabs = _records_writing(result, "/etc/fstab")
    assert len(fstabs) == 2
    for record in fstabs:
        text = record.stdin_text or ""
        assert "UUID=12AB-34CD /boot/efi vfat" in text
        assert "UUID=33333333-3333-4333-8333-333333333333 none swap" in text
    assert "UUID=11111111-1111-4111-8111-111111111111 / ext4" in (fstabs[0].stdin_text or "")
    assert "UUID=22222222-2222-4222-8222-222222222222 / ext4" in (fstabs[1].stdin_text or "")

    hostnames = [record.stdin_text for record in _records_writing(result, "/etc/hostname")]
    assert hostnames == ["workstation\n", "homeserver\n"]
    sshd = _records_writing(result, "/etc/ssh/sshd_config.d/90-uli.conf")
    assert len(sshd) == 2
    assert all("PasswordAuthentication no" in (record.stdin_text or "") for record in sshd)

    displays = "\n".join(record.display for record in result.commands)
    assert "$6$rounds=10000$salt$hash" not in displays
    password_commands = [record for record in result.commands if "chpasswd" in record.argv]
    assert len(password_commands) == 2
    assert all(record.sensitive_input and record.stdin_text is None for record in password_commands)
    assert all("bash" not in record.argv and "sh" not in record.argv for record in result.commands)

    all_argv = [record.argv for record in result.commands]
    assert any("task-gnome-desktop" in argv for argv in all_argv)
    assert any("tasksel" in argv and "install" in argv and "standard" in argv for argv in all_argv)
    assert any("ubuntu-standard" in argv and "openssh-server" in argv for argv in all_argv)
    assert (
        sum(
            "systemctl" in argv and "enable" in argv and "NetworkManager.service" in argv
            for argv in all_argv
        )
        == 2
    )
    assert sum("update-initramfs" in argv for argv in all_argv) == 2


def test_keyboard_mapping_writes_de_nodeadkeys_as_layout_and_variant() -> None:
    plan = _plan()
    plan.locale.keyboard = "de-nodeadkeys"
    result = provision_plan(plan, dry_run=True, mount_root="/mnt/uli-test")

    assert keyboard_configuration("de-nodeadkeys") == ("de", "nodeadkeys")
    keyboards = _records_writing(result, "/etc/default/keyboard")
    assert len(keyboards) == 2
    assert all('XKBLAYOUT="de"' in (record.stdin_text or "") for record in keyboards)
    assert all('XKBVARIANT="nodeadkeys"' in (record.stdin_text or "") for record in keyboards)

    plan.locale.keyboard = "de-arbitrary"
    with pytest.raises(ProvisioningError, match="Unsupported keyboard layout"):
        provision_plan(plan, dry_run=True)


def test_timezone_validation_requires_regular_file_below_zoneinfo(tmp_path: Path) -> None:
    zoneinfo = tmp_path / "zoneinfo"
    (zoneinfo / "Europe").mkdir(parents=True)
    (zoneinfo / "Europe" / "Berlin").write_bytes(b"TZif-test")
    (zoneinfo / "Etc").mkdir()
    (zoneinfo / "Etc" / "UTC").write_bytes(b"TZif-test")
    (zoneinfo / "UTC").symlink_to("Etc/UTC")

    assert validate_host_timezone("Europe/Berlin", zoneinfo_root=zoneinfo).name == "Berlin"
    assert validate_host_timezone("UTC", zoneinfo_root=zoneinfo).name == "UTC"

    (zoneinfo / "posix" / "Europe").mkdir(parents=True)
    (zoneinfo / "posix" / "Europe" / "Berlin").write_bytes(b"TZif-test")
    with pytest.raises(ProvisioningError, match="Unsupported timezone"):
        validate_host_timezone("posix/Europe/Berlin", zoneinfo_root=zoneinfo)
    with pytest.raises(ProvisioningError, match="Unsupported timezone"):
        validate_host_timezone("Europe/../Etc/UTC", zoneinfo_root=zoneinfo)

    (zoneinfo / "Europe" / "Directory").mkdir()
    with pytest.raises(ProvisioningError, match="regular tzdata file"):
        validate_host_timezone("Europe/Directory", zoneinfo_root=zoneinfo)

    outside = tmp_path / "outside"
    outside.write_bytes(b"TZif-test")
    (zoneinfo / "Europe" / "Escape").symlink_to(outside)
    with pytest.raises(ProvisioningError, match="regular tzdata file"):
        validate_host_timezone("Europe/Escape", zoneinfo_root=zoneinfo)


@pytest.mark.parametrize(
    "username",
    ["root", "_apt", "messagebus", "polkitd", "sssd", "gnome-remote-desktop", "kernoops"],
)
def test_provisioning_rejects_reserved_system_accounts(username: str) -> None:
    plan = _plan()
    plan.user.username = username

    with pytest.raises(ProvisioningError, match="reserved for a system account"):
        provision_plan(plan, dry_run=True)


def test_real_preflight_validates_timezone_but_dry_run_is_host_independent(monkeypatch) -> None:
    from uli.install import job

    plan = _plan()
    calls: list[str] = []

    def reject_timezone(timezone: str) -> None:
        calls.append(timezone)
        raise ProvisioningError("timezone sentinel")

    monkeypatch.setattr(job, "validate_host_timezone", reject_timezone)
    job._preflight_installation(plan, dry_run=True)
    assert calls == []

    with pytest.raises(ProvisioningError, match="timezone sentinel"):
        job._preflight_installation(plan, dry_run=False)
    assert calls == ["Europe/Berlin"]


def test_real_preflight_requires_efibootmgr_before_storage(monkeypatch) -> None:
    from uli.install import job

    plan = _plan()
    monkeypatch.setattr(job, "validate_host_timezone", lambda _timezone: None)
    monkeypatch.setattr(
        job.shutil,
        "which",
        lambda name: None if name == "efibootmgr" else f"/usr/bin/{name}",
    )
    with pytest.raises(RuntimeError, match="efibootmgr"):
        job._preflight_installation(plan, dry_run=False)


def test_provision_cleanup_is_reverse_order_and_root_is_last() -> None:
    plan = _plan()
    plan.distributions = plan.distributions[:1]
    plan.partitions = [part for part in plan.partitions if part.distribution in {None, "debian"}]
    result = provision_plan(plan, dry_run=True, mount_root="/mnt/uli-test")
    unmounts = [record.argv for record in result.commands if "umount" in record.argv]

    assert [argv[-1].rsplit("/", 1)[-1] for argv in unmounts[-5:]] == [
        "run",
        "sys",
        "proc",
        "dev",
        "01-debian-desktop",
    ]


def test_unsupported_distribution_and_missing_uuid_fail_before_commands() -> None:
    plan = _plan()
    plan.distributions[0] = DistroSelection("fedora", "server", "Fedora Server")
    runner = CommandRunner(dry_run=True, use_sudo=False)
    with pytest.raises(UnsupportedDistributionError, match="only for Debian 13 and Ubuntu LTS"):
        Provisioner(plan, runner=runner).provision_all()
    assert runner.commands == []

    plan = _plan()
    plan.partitions[1].uuid = None
    with pytest.raises(ProvisioningError, match="Missing filesystem UUID"):
        provision_plan(plan, dry_run=True)


def test_same_distro_variants_map_to_distinct_root_partitions() -> None:
    plan = _plan()
    plan.distributions = [
        DistroSelection("ubuntu", "desktop", "Ubuntu Desktop", hostname="workstation"),
        DistroSelection("ubuntu", "server", "Ubuntu Server", hostname="server"),
    ]
    plan.partitions[1].distribution = "ubuntu:desktop"
    plan.partitions[1].label = "root-ubuntu-d266"
    plan.partitions[2].distribution = "ubuntu:server"
    plan.partitions[2].label = "root-ubuntu-4ad7"

    provisioner = Provisioner(plan, runner=CommandRunner(dry_run=True, use_sudo=False))
    assert provisioner.root_partition(plan.distributions[0]) is plan.partitions[1]
    assert provisioner.root_partition(plan.distributions[1]) is plan.partitions[2]


def test_ssh_server_is_controlled_only_by_explicit_setting() -> None:
    plan = _plan()
    plan.user.install_ssh_server = False
    plan.user.disable_password_auth = False
    result = provision_plan(plan, dry_run=True)
    all_argv = [record.argv for record in result.commands]
    assert not any("openssh-server" in argv for argv in all_argv)
    assert not _records_writing(result, "/etc/ssh/sshd_config.d/90-uli.conf")

    plan.user.disable_password_auth = True
    with pytest.raises(ProvisioningError, match="requires install_ssh_server"):
        provision_plan(plan, dry_run=True)

    plan.user.install_ssh_server = True
    plan.user.ssh_keys = []
    with pytest.raises(ProvisioningError, match="At least one SSH public key"):
        provision_plan(plan, dry_run=True)


def test_grub_cfg_uses_real_uuids_theme_and_firmware_entry_is_last() -> None:
    cfg = render_grub_cfg(_plan(), require_uuids=True)
    assert "PENDING-" not in cfg
    assert "set timeout=7" in cfg
    assert "set default=1" in cfg
    assert "search --no-floppy --fs-uuid --set=uli_esp 12AB-34CD" in cfg
    assert "EFI/UltimateInstaller/themes/uli-lenovo/theme.txt" in cfg
    assert "root=UUID=11111111-1111-4111-8111-111111111111" in cfg
    assert cfg.rfind("menuentry 'UEFI Firmware Settings'") > cfg.rfind("Ubuntu 26.04 Server")


def test_chef_grub_dry_run_plans_check_standalone_fallback_then_nvram() -> None:
    result = install_chef_grub(
        _plan(),
        dry_run=True,
        mount_root="/mnt/uli-esp-test",
    )
    displays = [record.display for record in result.commands]

    check_indexes = [index for index, value in enumerate(displays) if "grub-script-check" in value]
    standalone_index = next(
        index for index, value in enumerate(displays) if "grub-mkstandalone" in value
    )
    nvram_index = next(
        index for index, value in enumerate(displays) if "efibootmgr --create" in value
    )
    unmount_index = max(
        index for index, value in enumerate(displays) if "umount --recursive" in value
    )
    assert len(check_indexes) == 2
    assert max(check_indexes) < standalone_index < unmount_index < nvram_index
    assert any("EFI/UltimateInstaller/grubx64.efi" in value for value in displays)
    assert any("EFI/BOOT/BOOTX64.EFI" in value for value in displays)
    assert result.loader_path == "EFI/UltimateInstaller/grubx64.efi"
    assert result.fallback_path == "EFI/BOOT/BOOTX64.EFI"


def test_real_grub_preflight_runs_syntax_fonts_and_standalone(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from uli.bootloader import grub
    from uli.install.runner import CommandOutcome, CommandRecord

    calls: list[tuple[str, ...]] = []

    def fake_run(self, argv, **_kwargs):
        call = tuple(str(value) for value in argv)
        calls.append(call)
        for value in call:
            if value.startswith("--output="):
                Path(value.partition("=")[2]).write_bytes(b"MZ" + b"x" * 100_000)
        record = CommandRecord(argv=call)
        self._commands.append(record)
        return CommandOutcome(record=record, returncode=0)

    fonts = tuple(
        (name, size, tmp_path / f"source-{index}.ttf")
        for index, (name, size, _source) in enumerate(grub._THEME_FONTS)
    )
    for _name, _size, source in fonts:
        source.write_bytes(b"font")
    unicode_font = tmp_path / "unicode.pf2"
    unicode_font.write_bytes(b"font")
    module_root = tmp_path / "modules"
    module_root.mkdir()

    monkeypatch.setattr(grub, "_THEME_FONTS", fonts)
    monkeypatch.setattr("uli.install.runner.CommandRunner.require_tools", lambda self, names: None)
    monkeypatch.setattr("uli.install.runner.CommandRunner.run", fake_run)
    original_is_dir = Path.is_dir
    original_is_file = Path.is_file
    monkeypatch.setattr(
        Path,
        "is_dir",
        lambda self: True if self == Path("/usr/lib/grub/x86_64-efi") else original_is_dir(self),
    )
    monkeypatch.setattr(
        Path,
        "is_file",
        lambda self: True if self == Path("/usr/share/grub/unicode.pf2") else original_is_file(self),
    )

    commands = preflight_chef_grub_build(_plan())
    assert sum(call[0] == "grub-script-check" for call in calls) == 2
    assert sum(call[0] == "grub-mkfont" for call in calls) == 4
    standalone = next(call for call in calls if call[0] == "grub-mkstandalone")
    assert "--compress=none" in standalone
    assert len(commands) == 7


def test_secure_boot_detection_and_rejection(tmp_path: Path) -> None:
    efivars = tmp_path / "efivars"
    efivars.mkdir()
    variable = efivars / "SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"
    variable.write_bytes(b"\x07\x00\x00\x00\x01")
    assert secure_boot_enabled(efivars) is True
    variable.write_bytes(b"\x07\x00\x00\x00\x00")
    assert secure_boot_enabled(efivars) is False

    variable.unlink()
    with pytest.raises(GrubInstallError, match="unknown"):
        secure_boot_enabled(efivars, require_known=True)

    with pytest.raises(UnsupportedSecureBootError):
        validate_uefi_environment(dry_run=True, secure_boot=True)


@pytest.mark.parametrize(
    "payload",
    [b"\x07\x00\x00\x00\x00\x00", b"\x07\x00\x00\x00\x02"],
)
def test_secure_boot_detection_rejects_malformed_standard_variable(
    tmp_path: Path,
    payload: bytes,
) -> None:
    efivars = tmp_path / "efivars"
    efivars.mkdir()
    (efivars / "SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c").write_bytes(payload)
    with pytest.raises(GrubInstallError, match="invalid payload"):
        secure_boot_enabled(efivars, require_known=True)


def test_secure_boot_detection_ignores_foreign_named_variable(tmp_path: Path) -> None:
    efivars = tmp_path / "efivars"
    efivars.mkdir()
    (efivars / "SecureBoot-00000000-0000-0000-0000-000000000000").write_bytes(
        b"\x07\x00\x00\x00\x00"
    )
    (efivars / "SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c").write_bytes(
        b"\x07\x00\x00\x00\x01"
    )
    assert secure_boot_enabled(efivars, require_known=True) is True


def test_nvram_match_is_bound_to_active_current_esp() -> None:
    current = "A8B1F8A8-8CE6-4F0C-A2F5-0B78BE2B6E2A"
    stale = "11111111-2222-4333-8444-555555555555"
    output = (
        "BootOrder: 000A,000B,000C\n"
        f"Boot000A* UltimateInstaller  HD(1,GPT,{stale},0x800,0x80000)/File(\\EFI\\UltimateInstaller\\grubx64.efi)\n"
        f"Boot000B  UltimateInstaller  HD(1,GPT,{current},0x800,0x80000)/File(\\EFI\\UltimateInstaller\\grubx64.efi)\n"
        f"Boot000C* UltimateInstaller  PciRoot(0x0)/Pci(0x1,0x1)/HD(1,GPT,{current},0x800,0x80000)/File(\\EFI\\ULTIMATEINSTALLER\\GRUBX64.EFI)\n"
    )
    assert _find_chef_boot_number(
        output,
        "UltimateInstaller",
        esp_partuuid=current.lower(),
        part_number=1,
    ) == "000C"
    assert _find_chef_boot_number(
        output,
        "UltimateInstaller",
        esp_partuuid=current,
        part_number=2,
    ) is None


@pytest.mark.parametrize(
    "invalid_entry",
    [
        (
            "Boot000D* UltimateInstaller-old  HD(1,GPT,{partuuid},0x800,0x80000)"
            "/File(\\EFI\\UltimateInstaller\\grubx64.efi)"
        ),
        (
            "Boot000D* UltimateInstaller  HD(1,GPT,{partuuid},0x800,0x80000)"
            "/File(\\EFI\\UltimateInstaller\\grubx64.efi.backup)"
        ),
    ],
)
def test_nvram_match_rejects_similar_label_and_loader(invalid_entry: str) -> None:
    current = "A8B1F8A8-8CE6-4F0C-A2F5-0B78BE2B6E2A"
    output = invalid_entry.format(partuuid=current)

    assert _find_chef_boot_number(
        output,
        "UltimateInstaller",
        esp_partuuid=current,
        part_number=1,
    ) is None


def test_verify_system_requires_resolved_nonempty_kernel_links() -> None:
    plan = _plan()
    runner = CommandRunner(dry_run=True, use_sudo=False)
    provisioner = Provisioner(plan, runner=runner)

    provisioner._verify_system(Path("/mnt/root"))

    commands = [record.argv[-3:] for record in runner.commands]
    for path in ("/vmlinuz", "/initrd.img"):
        assert ("test", "-L", path) in commands
        assert ("readlink", "-e", path) in commands
        assert ("test", "-s", path) in commands


def test_debian_tasksel_standard_runs_after_tasksel_package() -> None:
    plan = _plan()
    plan.mode = "simple"
    plan.distributions = [
        DistroSelection(
            "debian",
            "server",
            "Debian Server",
            release="trixie",
            hostname="debserver",
        )
    ]
    plan.partitions = [
        part
        for part in plan.partitions
        if part.role in {"esp", "swap"} or (part.distribution or "").startswith("debian")
    ]
    for part in plan.partitions:
        if part.role == "root":
            part.distribution = "debian:server"

    result = provision_plan(plan, dry_run=True, mount_root="/mnt/uli-test")
    argv_list = [record.argv for record in result.commands]

    def has_tasksel_apt(argv: tuple[str, ...]) -> bool:
        return "apt-get" in argv and "install" in argv and "tasksel" in argv

    def is_tasksel_standard(argv: tuple[str, ...]) -> bool:
        return list(argv[-3:]) == ["tasksel", "install", "standard"]

    apt_indexes = [index for index, argv in enumerate(argv_list) if has_tasksel_apt(argv)]
    tasksel_indexes = [index for index, argv in enumerate(argv_list) if is_tasksel_standard(argv)]
    assert apt_indexes and tasksel_indexes
    assert apt_indexes[0] < tasksel_indexes[0]
    assert all("task-gnome-desktop" not in argv for argv in argv_list)


def test_debian_desktop_includes_gnome_metapackage_and_tasksel_standard() -> None:
    plan = _plan()
    result = provision_plan(plan, dry_run=True, mount_root="/mnt/uli-test")
    argv_list = [record.argv for record in result.commands]
    assert any("task-gnome-desktop" in argv for argv in argv_list)
    assert any(list(argv[-3:]) == ["tasksel", "install", "standard"] for argv in argv_list)


def test_tasksel_standard_failure_is_not_swallowed() -> None:
    from uli.install.runner import CommandExecutionError, CommandOutcome, CommandRecord

    plan = _plan()
    plan.mode = "simple"
    plan.distributions = [
        DistroSelection(
            "debian",
            "server",
            "Debian Server",
            release="trixie",
            hostname="debserver",
        )
    ]
    plan.partitions = [
        part
        for part in plan.partitions
        if part.role in {"esp", "swap"} or (part.distribution or "").startswith("debian")
    ]
    for part in plan.partitions:
        if part.role == "root":
            part.distribution = "debian:server"

    class BoomRunner(CommandRunner):
        def run(self, argv, **kwargs):  # type: ignore[no-untyped-def]
            raw = tuple(str(item) for item in argv)
            if list(raw[-3:]) == ["tasksel", "install", "standard"]:
                record = CommandRecord(argv=raw)
                raise CommandExecutionError(
                    CommandOutcome(record=record, returncode=1, stderr="tasksel failed")
                )
            return super().run(argv, **kwargs)

    with pytest.raises(CommandExecutionError, match="tasksel failed"):
        provision_plan(
            plan,
            dry_run=True,
            runner=BoomRunner(dry_run=True, use_sudo=False),
            mount_root="/mnt/uli-test",
        )


def test_grub_refuses_missing_real_uuid() -> None:
    plan = _plan()
    plan.partitions[0].uuid = None
    with pytest.raises(GrubInstallError, match="Missing EFI"):
        install_chef_grub(plan, dry_run=True)
