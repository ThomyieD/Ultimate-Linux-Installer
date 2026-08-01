"""Debian adapter – preseed automation."""

from __future__ import annotations

from textwrap import dedent
from typing import Any

from uli.bootloader import grub as grubmod
from uli.core.adapters import AdapterInfo, register
from uli.core.plan import DistroSelection, InstallationPlan


class DebianAdapter:
    info = AdapterInfo(
        id="debian",
        family="debian",
        display_name="Debian",
        variants=("desktop", "server"),
        installation_modes=("simple", "multiboot", "add"),
        automation="preseed",
        minimum_root_gib=20,
        supports_desktop=True,
        supports_server=True,
        icon="debian",
    )

    def resolve_release(self, selection: DistroSelection) -> dict[str, Any]:
        return {
            "id": "debian",
            "codename": "trixie",
            "version": "13",
            "mirror": "https://deb.debian.org/debian",
            "netboot_kernel": "https://deb.debian.org/debian/dists/trixie/main/installer-amd64/current/images/netboot/debian-installer/amd64/linux",
            "netboot_initrd": "https://deb.debian.org/debian/dists/trixie/main/installer-amd64/current/images/netboot/debian-installer/amd64/initrd.gz",
            "checksum_url": "https://deb.debian.org/debian/dists/trixie/main/installer-amd64/current/images/SHA256SUMS",
        }

    def generate_automation(
        self, plan: InstallationPlan, selection: DistroSelection
    ) -> dict[str, str]:
        root = next(
            p for p in plan.partitions if p.role == "root" and p.distribution == "debian"
        )
        desktop = selection.variant == "desktop"
        pkgs = "sudo openssh-server"
        if desktop:
            pkgs += " task-gnome-desktop"
        preseed = dedent(
            f"""\
            # Ultimate Linux Installer – Debian preseed
            d-i debian-installer/locale string {plan.locale.language}
            d-i keyboard-configuration/xkb-keymap select {plan.locale.keyboard}
            d-i netcfg/choose_interface select auto
            d-i mirror/country string manual
            d-i mirror/http/hostname string deb.debian.org
            d-i mirror/http/directory string /debian
            d-i mirror/http/proxy string

            d-i partman-auto/method string regular
            d-i partman-auto/disk string {plan.disk.path}
            # Multiboot: ULI partitions beforehand; installer uses existing partitions
            d-i partman/early_command string debconf-set partman-auto/disk {plan.disk.path}

            d-i passwd/user-fullname string {plan.user.username}
            d-i passwd/user-password-crypted password {plan.user.password_hash or "*"}
            d-i passwd/root-login boolean false
            d-i user-setup/allow-password-weak boolean true
            d-i user-setup/encrypt-home boolean false

            d-i time/zone string {plan.locale.timezone}
            d-i clock-setup/utc boolean true

            tasksel tasksel/first multiselect standard${", desktop" if desktop else ""}
            d-i pkgsel/include string {pkgs}
            d-i pkgsel/upgrade select full-upgrade

            d-i grub-installer/only_debian boolean false
            d-i grub-installer/with_other_os boolean false
            d-i grub-installer/bootdev string none
            d-i finish-install/reboot_in_progress note

            d-i preseed/late_command string \\
                in-target bash -c 'echo label={root.label} >/dev/null'; \\
                in-target bash -c '{grubmod.render_sudo_user_guard(plan.user.username).replace(chr(10), "; ")}'
            """
        )
        return {"preseed.cfg": preseed}

    def post_install_hooks(self, plan: InstallationPlan, selection: DistroSelection) -> list[str]:
        hooks = [grubmod.render_kernel_symlink_hook("debian")]
        hooks.append(grubmod.render_sudo_user_guard(plan.user.username))
        swap = next((p for p in plan.partitions if p.role == "swap"), None)
        if swap and swap.uuid:
            hooks.append(grubmod.render_fstab_swap_guard(swap.uuid))
        return hooks


register(DebianAdapter())
