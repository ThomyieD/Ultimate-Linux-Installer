"""Fedora adapter – Kickstart."""

from __future__ import annotations

from textwrap import dedent
from typing import Any

from uli.bootloader import grub as grubmod
from uli.core.adapters import AdapterInfo, register
from uli.core.plan import DistroSelection, InstallationPlan


class FedoraAdapter:
    info = AdapterInfo(
        id="fedora",
        family="redhat",
        display_name="Fedora",
        variants=("workstation", "server"),
        installation_modes=("simple", "multiboot", "add"),
        automation="kickstart",
        minimum_root_gib=25,
        supports_desktop=True,
        supports_server=True,
        icon="fedora",
    )

    def resolve_release(self, selection: DistroSelection) -> dict[str, Any]:
        return {
            "id": "fedora",
            "version": "42",
            "mirror": "https://download.fedoraproject.org/pub/fedora/linux/releases/42/",
            "checksum_url": "https://getfedora.org/static/checksums/",
        }

    def generate_automation(
        self, plan: InstallationPlan, selection: DistroSelection
    ) -> dict[str, str]:
        desktop = selection.variant == "workstation"
        root = next(p for p in plan.partitions if p.role == "root" and p.distribution == "fedora")
        ks = dedent(
            f"""\
            # Ultimate Linux Installer – Fedora Kickstart
            lang {plan.locale.language}
            keyboard {plan.locale.keyboard}
            timezone {plan.locale.timezone} --utc
            network --bootproto=dhcp --activate
            rootpw --lock
            user --name={plan.user.username} --groups=wheel --password={plan.user.password_hash or "!"} --iscrypted
            firewall --enabled --ssh
            selinux --enforcing
            bootloader --location=none
            # ULI owns GPT layout; use preexisting partition by label when possible
            clearpart --none
            mount --opts=defaults --device=LABEL={root.label} /

            %packages
            @core
            {"@workstation-product-environment" if desktop else "@server-product-environment"}
            %end

            %post
            {grubmod.render_sudo_user_guard(plan.user.username)}
            {grubmod.render_kernel_symlink_hook("fedora")}
            %end
            """
        )
        return {"fedora.ks": ks}

    def post_install_hooks(self, plan: InstallationPlan, selection: DistroSelection) -> list[str]:
        return [
            grubmod.render_kernel_symlink_hook("fedora"),
            grubmod.render_sudo_user_guard(plan.user.username),
        ]


register(FedoraAdapter())
