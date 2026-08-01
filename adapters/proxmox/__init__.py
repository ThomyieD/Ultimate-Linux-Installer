"""Proxmox VE adapter – official automated ISO answer file (simple mode only)."""

from __future__ import annotations

from textwrap import dedent
from typing import Any

from uli.core.adapters import AdapterInfo, register
from uli.core.plan import DistroSelection, InstallationPlan


class ProxmoxAdapter:
    info = AdapterInfo(
        id="proxmox",
        family="special",
        display_name="Proxmox VE",
        variants=("ve",),
        installation_modes=("simple",),  # never multiboot
        automation="answer.toml",
        minimum_root_gib=32,
        supports_desktop=False,
        supports_server=True,
        icon="proxmox",
    )

    def resolve_release(self, selection: DistroSelection) -> dict[str, Any]:
        return {
            "id": "proxmox",
            "version": "8",
            "iso_page": "https://www.proxmox.com/en/downloads",
            "docs": "https://pve.proxmox.com/wiki/Automated_Installation",
        }

    def generate_automation(
        self, plan: InstallationPlan, selection: DistroSelection
    ) -> dict[str, str]:
        if plan.mode != "simple":
            raise ValueError("Proxmox is only supported in simple installation mode")
        answer = dedent(
            f"""\
            # Ultimate Linux Installer – Proxmox automated answer file
            [global]
            keyboard = "{plan.locale.keyboard}"
            country = "de"
            fqdn = "proxmox.local"
            mailto = "root@proxmox.local"
            timezone = "{plan.locale.timezone}"
            root-password-hashed = "{plan.user.password_hash or ""}"

            [network]
            source = "from-dhcp"

            [disk-setup]
            filesystem = "ext4"
            disk-list = ["{plan.disk.path.split('/')[-1]}"]
            """
        )
        return {"answer.toml": answer}

    def post_install_hooks(self, plan: InstallationPlan, selection: DistroSelection) -> list[str]:
        return []


register(ProxmoxAdapter())
