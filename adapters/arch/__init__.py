"""Arch adapter – pacstrap / archinstall oriented."""

from __future__ import annotations

import json
from typing import Any

from uli.bootloader import grub as grubmod
from uli.core.adapters import AdapterInfo, register
from uli.core.plan import DistroSelection, InstallationPlan


class ArchAdapter:
    info = AdapterInfo(
        id="arch",
        family="arch",
        display_name="Arch Linux",
        variants=("desktop",),
        installation_modes=("simple", "multiboot", "add"),
        automation="pacstrap",
        minimum_root_gib=20,
        supports_desktop=True,
        supports_server=True,
        icon="arch",
    )

    def resolve_release(self, selection: DistroSelection) -> dict[str, Any]:
        return {
            "id": "arch",
            "version": "rolling",
            "mirrorlist": "https://archlinux.org/mirrorlist/?country=all&protocol=https&use_mirror_status=on",
            "bootstrap": "https://geo.mirror.pkgbuild.com/iso/latest/",
        }

    def generate_automation(
        self, plan: InstallationPlan, selection: DistroSelection
    ) -> dict[str, str]:
        root = next(
            p
            for p in plan.partitions
            if p.role == "root"
            and p.distribution in {"arch", f"arch:{selection.variant}"}
        )
        cfg = {
            "disk": plan.disk.path,
            "root_label": root.label,
            "hostname": "arch",
            "username": plan.user.username,
            "password_hash": plan.user.password_hash,
            "ssh_keys": plan.user.ssh_keys,
            "timezone": plan.locale.timezone,
            "packages": [
                "base",
                "linux",
                "linux-firmware",
                "networkmanager",
                "sudo",
                "openssh",
                "grub",
                "efibootmgr",
            ],
            "bootloader": "none",  # ULI central GRUB
            "notes": "Use pacstrap into the prepared root; do not install distro GRUB as chef.",
        }
        script = "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "# Ultimate Linux Installer – Arch pacstrap scaffold",
                f'ROOT_LABEL="{root.label}"',
                'ROOT_DEV=$(blkid -L "$ROOT_LABEL")',
                'mount "$ROOT_DEV" /mnt',
                "pacstrap -K /mnt base linux linux-firmware networkmanager sudo openssh",
                "genfstab -U /mnt >> /mnt/etc/fstab",
                f"arch-chroot /mnt useradd -m -G wheel -s /bin/bash {plan.user.username}",
                grubmod.render_sudo_user_guard(plan.user.username),
                grubmod.render_kernel_symlink_hook("arch"),
            ]
        )
        return {
            "archinstall.json": json.dumps(cfg, indent=2),
            "pacstrap.sh": script + "\n",
        }

    def post_install_hooks(self, plan: InstallationPlan, selection: DistroSelection) -> list[str]:
        return [
            grubmod.render_kernel_symlink_hook("arch"),
            grubmod.render_sudo_user_guard(plan.user.username),
        ]


register(ArchAdapter())
