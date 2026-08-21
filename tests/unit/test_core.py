from __future__ import annotations

import pytest
from uli.bootloader.grub import build_menu_entries, render_grub_cfg
from uli.core.plan import (
    BootloaderConfig,
    DiskTarget,
    DistroSelection,
    InstallationPlan,
    NetworkConfig,
    PartitionSpec,
    UserConfig,
    plan_from_dict,
)
from uli.storage.layout import equal_root_layout, validate_layout


def test_legacy_qt_ui_requires_dry_run() -> None:
    from uli.main import main

    with pytest.raises(SystemExit) as exc:
        main(["--ui", "qt"])
    assert exc.value.code == 2


def _sample_plan() -> InstallationPlan:
    distros = [
        DistroSelection("ubuntu", "desktop", "Ubuntu Desktop"),
        DistroSelection("debian", "desktop", "Debian Desktop"),
        DistroSelection("fedora", "workstation", "Fedora Workstation"),
    ]
    parts, _warnings = equal_root_layout(512 * 1024**3, distros)
    # Assign fake UUIDs as the live installer would after mkfs
    for i, p in enumerate(parts):
        if p.role == "root":
            p.uuid = f"11111111-1111-1111-1111-{i:012d}"
        if p.role == "swap":
            p.uuid = "22222222-2222-2222-2222-222222222222"
    return InstallationPlan(
        mode="multiboot",
        disk=DiskTarget(id="sim", path="/dev/nvme0n1", size_bytes=512 * 1024**3),
        partitions=parts,
        distributions=distros,
        user=UserConfig(username="t", password_hash="$6$test$hash"),
        bootloader=BootloaderConfig(theme="uli-lenovo", timeout_seconds=5),
        confirmed=True,
    )


def test_equal_layout_has_esp_and_roots():
    distros = [
        DistroSelection("ubuntu", "desktop", "Ubuntu Desktop"),
        DistroSelection("arch", "desktop", "Arch Linux"),
    ]
    parts, _warnings = equal_root_layout(256 * 1024**3, distros)
    assert any(p.role == "esp" for p in parts)
    assert len([p for p in parts if p.role == "root"]) == 2
    assert validate_layout(parts, 256 * 1024**3) == []


def test_grub_menu_order_and_firmware_last():
    plan = _sample_plan()
    cfg = render_grub_cfg(plan)
    assert "set timeout=5" in cfg
    assert "timeout_style=menu" in cfg
    assert cfg.index("Ubuntu Desktop") < cfg.index("UEFI Firmware Settings")
    assert "Advanced options" not in cfg
    entries = build_menu_entries(plan)
    assert entries[0].title == "Ubuntu Desktop"
    assert "resume=UUID=22222222-2222-2222-2222-222222222222" in entries[0].options


def test_proxmox_only_simple():
    from uli.core.catalog import catalog_for_mode

    multi = {e.id for e in catalog_for_mode("multiboot")}
    simple = {e.id for e in catalog_for_mode("simple")}
    assert "proxmox" not in multi
    assert "proxmox" in simple


def test_storage_guard_requires_confirmation():
    from uli.storage.executor import StorageGuard

    guard = StorageGuard(dry_run=True)
    try:
        guard.apply_partition_table(
            "/dev/sda",
            [],
            confirmed=False,
            mode="simple",
            wipe=True,
        )
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


def test_adapters_generate_files():
    from uli.core.adapters import get_adapter

    plan = _sample_plan()
    for distro in plan.distributions:
        adapter = get_adapter(distro.id)
        files = adapter.generate_automation(plan, distro)
        assert files
        hooks = adapter.post_install_hooks(plan, distro)
        assert any("vmlinuz" in h for h in hooks)


def test_plan_round_trip_preserves_provisioning_options_and_partuuids():
    plan = _sample_plan()
    plan.distributions[0].hostname = "workstation"
    plan.user.install_ssh_server = False
    plan.bootloader.default_entry = "ubuntu"
    plan.network = NetworkConfig(method="dhcp", persist=False)

    restored = plan_from_dict(plan.to_dict())

    assert restored.distributions[0].hostname == "workstation"
    assert restored.user.install_ssh_server is False
    assert restored.bootloader.default_entry == "ubuntu"
    assert restored.network.persist is False
    assert [part.partuuid for part in restored.partitions] == [
        part.partuuid for part in plan.partitions
    ]


def test_plan_rejects_duplicate_partuuids_and_wipe_in_mutation_mode():
    partuuid = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    partitions = [
        PartitionSpec(
            role="esp",
            size_mib=1024,
            filesystem="fat32",
            label="EFI",
            partuuid=partuuid,
        ),
        PartitionSpec(
            role="root",
            size_mib=20 * 1024,
            filesystem="ext4",
            label="root-linux",
            partuuid=partuuid,
        ),
    ]
    with pytest.raises(ValueError, match="Duplicate PARTUUID"):
        InstallationPlan(
            mode="simple",
            disk=DiskTarget("disk", "/dev/sda", 64 * 1024**3),
            partitions=partitions,
            distributions=[DistroSelection("linux", "desktop", "Linux")],
            user=UserConfig("user"),
        )

    with pytest.raises(ValueError, match="must never use a wipe plan"):
        InstallationPlan(
            mode="add",
            disk=DiskTarget("disk", "/dev/sda", 64 * 1024**3, wipe=True),
            partitions=[],
            distributions=[DistroSelection("linux", "desktop", "Linux")],
            user=UserConfig("user"),
        )


def test_disk_target_rejects_unsafe_device_path():
    with pytest.raises(ValueError, match="safe absolute path"):
        DiskTarget("disk", "/dev/sda;reboot", 64 * 1024**3)
