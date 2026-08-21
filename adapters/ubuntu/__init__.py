"""Ubuntu adapter – Subiquity autoinstall."""

from __future__ import annotations

from textwrap import dedent
from typing import Any

import yaml
from uli.bootloader import grub as grubmod
from uli.core.adapters import AdapterInfo, register
from uli.core.plan import DistroSelection, InstallationPlan


class UbuntuAdapter:
    info = AdapterInfo(
        id="ubuntu",
        family="debian",
        display_name="Ubuntu",
        variants=("desktop", "server"),
        installation_modes=("simple", "multiboot", "add"),
        automation="autoinstall",
        minimum_root_gib=25,
        supports_desktop=True,
        supports_server=True,
        icon="ubuntu",
    )

    def resolve_release(self, selection: DistroSelection) -> dict[str, Any]:
        flavor = "desktop" if selection.variant == "desktop" else "live-server"
        return {
            "id": "ubuntu",
            "version": "24.04",
            "codename": "noble",
            "mirror": "https://releases.ubuntu.com/24.04/",
            "iso_hint": f"ubuntu-24.04-*{flavor}*.iso",
            "checksum_url": "https://releases.ubuntu.com/24.04/SHA256SUMS",
        }

    def generate_automation(
        self, plan: InstallationPlan, selection: DistroSelection
    ) -> dict[str, str]:
        roots = [
            p
            for p in plan.partitions
            if p.role == "root"
            and p.distribution in {"ubuntu", f"ubuntu:{selection.variant}"}
        ]
        root = next(
            (p for p in roots if selection.variant in (p.label or "")),
            roots[0],
        )

        identity = {
            "hostname": f"ubuntu-{selection.variant}",
            "username": plan.user.username,
        }
        if plan.user.password_hash:
            identity["password"] = plan.user.password_hash

        autoinstall = {
            "autoinstall": {
                "version": 1,
                "locale": plan.locale.language,
                "keyboard": {"layout": plan.locale.keyboard},
                "identity": identity,
                "ssh": {
                    "install-server": True,
                    "allow-pw": not plan.user.disable_password_auth,
                    "authorized-keys": plan.user.ssh_keys,
                },
                "storage": {
                    "config": [
                        {
                            "type": "disk",
                            "id": "disk0",
                            "path": plan.disk.path,
                            "ptable": "gpt",
                            "wipe": "superblock" if plan.mode == "simple" else None,
                            "preserve": plan.mode != "simple",
                        }
                    ]
                },
                "late-commands": [
                    f"curtin in-target -- usermod -aG sudo {plan.user.username}",
                    # Prevent Ubuntu from becoming BootOrder chef – ULI reclaim happens later
                    "true",
                ],
                # Critical: do not let Subiquity own the system bootloader in multiboot
                "grub": {"reorder_uefi": False},
            }
        }
        # Remove null wipe key cleanliness
        disk_cfg = autoinstall["autoinstall"]["storage"]["config"][0]
        if disk_cfg.get("wipe") is None:
            disk_cfg.pop("wipe", None)

        user_data = "#cloud-config\n" + yaml.safe_dump(autoinstall, sort_keys=False)
        meta = "instance-id: uli-ubuntu\nlocal-hostname: ubuntu\n"
        return {
            "user-data": user_data,
            "meta-data": meta,
            "notes.txt": dedent(
                f"""\
                Target root label: {root.label}
                Variant: {selection.variant}
                ULI will reclaim BootOrder after this installer finishes.
                """
            ),
        }

    def post_install_hooks(self, plan: InstallationPlan, selection: DistroSelection) -> list[str]:
        hooks = [
            grubmod.render_kernel_symlink_hook("ubuntu"),
            grubmod.render_sudo_user_guard(plan.user.username),
            # Disable NetworkManager-wait-online delay observed on the laptop project
            "systemctl disable NetworkManager-wait-online.service 2>/dev/null || true",
            "systemctl disable systemd-networkd-wait-online.service 2>/dev/null || true",
        ]
        swap = next((p for p in plan.partitions if p.role == "swap"), None)
        if swap and swap.uuid:
            hooks.append(grubmod.render_fstab_swap_guard(swap.uuid))
        return hooks


register(UbuntuAdapter())
