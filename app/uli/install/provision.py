"""Install supported Debian-family systems into already formatted root slots.

This module owns *root filesystem provisioning only*.  Its caller must first
apply storage and refresh every PartitionSpec UUID/PARTUUID.  The central EFI
bootloader is installed separately by :func:`uli.bootloader.grub.install_chef_grub`.
"""

from __future__ import annotations

import re
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from uli.bootloader.grub import (
    UnsupportedSecureBootError,
    render_kernel_symlink_hook,
    validate_uefi_environment,
)
from uli.core.plan import DistroSelection, InstallationPlan, PartitionSpec
from uli.install.runner import CommandRecord, CommandRunner
from uli.install.sources import SourceInfo, source_for

ProgressCallback = Callable[[str, int, str], None]
LogCallback = Callable[[str], None]


class ProvisioningError(RuntimeError):
    """A plan cannot be provisioned safely or a provisioning stage failed."""


class UnsupportedDistributionError(ProvisioningError):
    """The direct provisioner has no honest implementation for this selection."""


@dataclass(frozen=True)
class ProvisionResult:
    completed: list[str]
    commands: list[CommandRecord]
    roots: dict[str, str]
    dry_run: bool


@dataclass(frozen=True)
class _DistroSpec:
    distro_id: str
    suite: str
    version: str
    mirror: str
    keyring: str
    keyring_package: str
    kernel_package: str
    sources: str
    base_packages: tuple[str, ...]
    server_packages: tuple[str, ...]
    desktop_packages: tuple[str, ...]


_DEBIAN = _DistroSpec(
    distro_id="debian",
    suite="trixie",
    version="13",
    mirror="https://deb.debian.org/debian",
    keyring="/usr/share/keyrings/debian-archive-keyring.gpg",
    keyring_package="debian-archive-keyring",
    kernel_package="linux-image-amd64",
    sources="""\
deb [signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] https://deb.debian.org/debian trixie main contrib non-free-firmware
deb [signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] https://deb.debian.org/debian trixie-updates main contrib non-free-firmware
deb [signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] https://security.debian.org/debian-security trixie-security main contrib non-free-firmware
""",
    base_packages=("firmware-linux",),
    server_packages=("task-standard",),
    desktop_packages=("task-standard", "task-gnome-desktop"),
)

_UBUNTU = _DistroSpec(
    distro_id="ubuntu",
    suite="resolute",
    version="26.04",
    mirror="https://archive.ubuntu.com/ubuntu",
    keyring="/usr/share/keyrings/ubuntu-archive-keyring.gpg",
    keyring_package="ubuntu-keyring",
    kernel_package="linux-generic",
    sources="""\
deb [signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] https://archive.ubuntu.com/ubuntu resolute main restricted universe multiverse
deb [signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] https://archive.ubuntu.com/ubuntu resolute-updates main restricted universe multiverse
deb [signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] https://archive.ubuntu.com/ubuntu resolute-security main restricted universe multiverse
""",
    base_packages=("linux-firmware",),
    server_packages=("ubuntu-standard",),
    desktop_packages=("ubuntu-standard", "ubuntu-desktop"),
)

_SPECS = {"debian": _DEBIAN, "ubuntu": _UBUNTU}
_APT_ENV = {
    "DEBIAN_FRONTEND": "noninteractive",
    "APT_LISTCHANGES_FRONTEND": "none",
    "LC_ALL": "C.UTF-8",
}
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
_GPT_UUID = re.compile(
    r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
)
_FAT_UUID = re.compile(r"^[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}$")
_SAFE_USER = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
_SAFE_HOSTNAME = re.compile(
    r"^(?=.{1,253}\.?$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)(?:\.(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?))*\.?$"
)
_SAFE_LOCALE = re.compile(r"^[A-Za-z]{2,3}_[A-Za-z]{2}(?:\.UTF-?8)?$")
_SAFE_TIMEZONE = re.compile(r"^[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)+$")

# These names already belong to base or early-boot service accounts on supported
# Debian/Ubuntu systems.  Creating the interactive user with one of them would
# either fail late or, worse, modify the privileges of a system account.
RESERVED_SYSTEM_USERNAMES = frozenset(
    {
        "_apt",
        "_chrony",
        "avahi",
        "avahi-autoipd",
        "backup",
        "bin",
        "colord",
        "cups-browsed",
        "cups-pk-helper",
        "daemon",
        "dnsmasq",
        "fwupd-refresh",
        "games",
        "gdm",
        "geoclue",
        "gnome-remote-desktop",
        "gnome-initial-setup",
        "gnats",
        "irc",
        "kernoops",
        "landscape",
        "list",
        "lp",
        "mail",
        "man",
        "messagebus",
        "nm-openvpn",
        "news",
        "nobody",
        "pollinate",
        "polkitd",
        "proxy",
        "pulse",
        "root",
        "rtkit",
        "saned",
        "speech-dispatcher",
        "sssd",
        "sshd",
        "statd",
        "sync",
        "sys",
        "syslog",
        "systemd-coredump",
        "systemd-network",
        "systemd-oom",
        "systemd-resolve",
        "systemd-timesync",
        "tcpdump",
        "tss",
        "uucp",
        "usbmux",
        "uuidd",
        "whoopsie",
        "www-data",
    }
)

_KEYBOARD_CONFIGURATIONS = {
    "de": ("de", ""),
    "de-nodeadkeys": ("de", "nodeadkeys"),
    "us": ("us", ""),
    "gb": ("gb", ""),
    "ch": ("ch", ""),
}
SUPPORTED_KEYBOARDS = frozenset(_KEYBOARD_CONFIGURATIONS)
_SPECIAL_TIMEZONE_TREES = frozenset({"posix", "right", "systemv"})


def keyboard_configuration(keyboard: str) -> tuple[str, str]:
    """Return the whitelisted XKB layout and variant for a UI keyboard ID."""
    try:
        return _KEYBOARD_CONFIGURATIONS[keyboard]
    except KeyError as exc:
        raise ProvisioningError(f"Unsupported keyboard layout: {keyboard!r}") from exc


def is_safe_timezone_name(timezone: str) -> bool:
    """Validate a canonical tzdata name without consulting the host filesystem."""
    if timezone == "UTC":
        return True
    if not _SAFE_TIMEZONE.fullmatch(timezone):
        return False
    parts = timezone.split("/")
    return (
        all(part not in {"", ".", ".."} for part in parts)
        and parts[0].casefold() not in _SPECIAL_TIMEZONE_TREES
    )


def validate_host_timezone(
    timezone: str,
    *,
    zoneinfo_root: str | Path = "/usr/share/zoneinfo",
) -> Path:
    """Resolve a timezone to a real regular tzdata file below ``zoneinfo_root``."""
    if not is_safe_timezone_name(timezone):
        raise ProvisioningError(f"Unsupported timezone: {timezone!r}")

    try:
        root = Path(zoneinfo_root).resolve(strict=True)
    except OSError as exc:
        raise ProvisioningError(f"Timezone database is unavailable: {zoneinfo_root}") from exc
    candidates = [root / timezone]
    if timezone == "UTC":
        candidates.append(root / "Etc" / "UTC")

    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
            mode = resolved.stat().st_mode
        except (OSError, ValueError):
            continue
        if stat.S_ISREG(mode):
            return resolved
    raise ProvisioningError(f"Timezone does not resolve to a regular tzdata file: {timezone!r}")


class Provisioner:
    """Provision Debian and the current Ubuntu LTS from signed official repos."""

    def __init__(
        self,
        plan: InstallationPlan,
        *,
        runner: CommandRunner | None = None,
        mount_root: str | Path = "/mnt/uli",
        progress: ProgressCallback | None = None,
        log: LogCallback | None = None,
    ) -> None:
        self.plan = plan
        self.log = log or (lambda _message: None)
        self.runner = runner or CommandRunner(log=self.log)
        self.mount_root = Path(mount_root)
        self.progress = progress or (lambda _phase, _percent, _message: None)

    def validate(self) -> None:
        self.plan.require_confirmed()
        if not self.mount_root.is_absolute() or self.mount_root == Path("/"):
            raise ProvisioningError("Provisioning mount_root must be an absolute subdirectory")
        if not self.plan.disk.path.startswith("/dev/") or ".." in Path(self.plan.disk.path).parts:
            raise ProvisioningError(f"Unsafe target disk path: {self.plan.disk.path!r}")
        if not self.plan.distributions:
            raise ProvisioningError("At least one distribution must be selected")
        if self.plan.network.method != "dhcp":
            raise ProvisioningError("Direct provisioning currently supports DHCP only")
        esp_parts = [part for part in self.plan.partitions if part.role == "esp"]
        if len(esp_parts) != 1:
            raise ProvisioningError("Exactly one EFI system partition is required")
        if esp_parts[0].filesystem != "fat32":
            raise ProvisioningError("EFI system partition must be FAT32")
        for role in ("swap", "data"):
            if sum(part.role == role for part in self.plan.partitions) > 1:
                raise ProvisioningError(f"At most one shared {role} partition is supported")
        swap_part = next((part for part in self.plan.partitions if part.role == "swap"), None)
        if swap_part is not None and swap_part.filesystem != "swap":
            raise ProvisioningError("Shared swap partition must use the swap filesystem")
        data_part = next((part for part in self.plan.partitions if part.role == "data"), None)
        if data_part is not None and data_part.filesystem != "ext4":
            raise ProvisioningError("Shared data partition must use ext4 in this MVP")
        requested_secure_boot = getattr(self.plan.bootloader, "secure_boot", None)
        if requested_secure_boot is True:
            raise UnsupportedSecureBootError(
                "Secure Boot is enabled; direct provisioning cannot install an unsigned chef GRUB"
            )
        self._validate_account_and_locale()

        seen_roots: set[int] = set()
        seen_hostnames: set[str] = set()
        for selection in self.plan.distributions:
            spec = _spec_for(selection)
            root = self.root_partition(selection)
            marker = id(root)
            if marker in seen_roots:
                raise ProvisioningError(
                    f"Root partition is assigned more than once: {selection.id}:{selection.variant}"
                )
            seen_roots.add(marker)
            _require_filesystem_uuid(root, f"root for {selection.id}:{selection.variant}")
            if root.filesystem != "ext4":
                raise ProvisioningError(
                    f"{selection.id}:{selection.variant} requires a formatted ext4 root in this MVP"
                )
            _validate_release(selection, spec)
            hostname = self.hostname_for(selection)
            _validate_hostname(hostname)
            if hostname in seen_hostnames:
                raise ProvisioningError(f"Hostname is assigned more than once: {hostname}")
            seen_hostnames.add(hostname)

        for part in self.plan.partitions:
            if part.role in {"esp", "swap", "data"}:
                _require_filesystem_uuid(part, part.role)

    def root_partition(self, selection: DistroSelection) -> PartitionSpec:
        roots = [
            part
            for part in self.plan.partitions
            if part.role == "root"
            and part.distribution in {selection.id, f"{selection.id}:{selection.variant}"}
        ]
        exact = [
            part
            for part in roots
            if part.distribution == f"{selection.id}:{selection.variant}"
        ]
        if len(exact) == 1:
            return exact[0]
        if not roots:
            raise ProvisioningError(f"No root partition for {selection.id}:{selection.variant}")
        matching = [part for part in roots if selection.variant in (part.label or "")]
        if len(matching) == 1:
            return matching[0]
        if len(roots) == 1:
            return roots[0]
        if not matching:
            raise ProvisioningError(
                f"Cannot map {selection.id}:{selection.variant} to one of its root partitions"
            )
        raise ProvisioningError(
            f"Multiple root partitions match {selection.id}:{selection.variant}"
        )

    def hostname_for(self, selection: DistroSelection) -> str:
        requested = getattr(selection, "hostname", None)
        return str(requested or f"{selection.id}-{selection.variant}").lower()

    def partition_device(self, part: PartitionSpec) -> str:
        if part.partuuid:
            _validate_identifier(part.partuuid, "PARTUUID")
            return f"/dev/disk/by-partuuid/{part.partuuid}"
        try:
            index = self.plan.partitions.index(part) + 1
        except ValueError as exc:
            raise ProvisioningError("Partition does not belong to this installation plan") from exc
        disk = self.plan.disk.path
        separator = "p" if any(token in disk for token in ("nvme", "mmcblk", "loop", "md")) else ""
        return f"{disk}{separator}{index}"

    def plan_commands(self) -> list[CommandRecord]:
        planning_runner = CommandRunner(
            dry_run=True,
            log=self.log,
            use_sudo=self.runner.use_sudo,
        )
        planner = Provisioner(
            self.plan,
            runner=planning_runner,
            mount_root=self.mount_root,
            log=self.log,
        )
        return planner.provision_all().commands

    def provision_all(self) -> ProvisionResult:
        self.validate()
        validate_uefi_environment(
            dry_run=self.runner.dry_run,
            secure_boot=None,
        )
        self.runner.require_tools(("debootstrap", "mount", "umount", "chroot"))
        command_offset = len(self.runner.commands)
        completed: list[str] = []
        roots: dict[str, str] = {}
        total = len(self.plan.distributions)
        self._emit("validate", 1, "Provisioning plan validated")

        for index, selection in enumerate(self.plan.distributions):
            key = f"{selection.id}:{selection.variant}"
            root_mount = self._mountpoint(selection, index)
            start = 2 + int(index * 94 / total)
            end = 2 + int((index + 1) * 94 / total)
            self.provision(selection, root_mount=root_mount, start=start, end=end)
            completed.append(key)
            roots[key] = str(root_mount)

        self._prepare_data_partition()
        self._emit("done", 100, "All root systems provisioned")
        return ProvisionResult(
            completed=completed,
            commands=self.runner.commands_since(command_offset),
            roots=roots,
            dry_run=self.runner.dry_run,
        )

    def provision(
        self,
        selection: DistroSelection,
        *,
        root_mount: str | Path | None = None,
        start: int = 2,
        end: int = 96,
    ) -> None:
        spec = _spec_for(selection)
        root_part = self.root_partition(selection)
        root_target = Path(root_mount) if root_mount is not None else self._mountpoint(selection, 0)
        device = self.partition_device(root_part)
        label = f"{selection.id}:{selection.variant}"

        self._emit("mount", start, f"Mounting {label} root")
        with self.runner.mounted(
            device,
            root_target,
            filesystem=root_part.filesystem,
            options=("--options", "rw"),
        ) as mounted_root:
            self._emit("bootstrap", _between(start, end, 8), f"Bootstrapping {label}")
            self._debootstrap(spec, mounted_root)
            with (
                self.runner.chroot_mounts(mounted_root),
                self._package_install_guard(mounted_root),
            ):
                self._emit("configure", _between(start, end, 30), f"Configuring {label}")
                self._configure_base(selection, spec, root_part, mounted_root)
                self._emit("packages", _between(start, end, 52), f"Installing {label} packages")
                self._install_packages(selection, spec, mounted_root)
                self._emit("account", _between(start, end, 72), f"Creating {label} account")
                self._configure_account_and_ssh(mounted_root)
                self._emit("kernel", _between(start, end, 84), f"Finalizing {label} kernel")
                self._configure_kernel(selection, mounted_root)
                self._finalize_system(mounted_root)
                self._verify_system(mounted_root)
        self._emit("provisioned", end, f"Provisioned {label}")

    def _debootstrap(self, spec: _DistroSpec, root: Path) -> None:
        if not self.runner.dry_run and not Path(spec.keyring).is_file():
            raise ProvisioningError(f"Archive keyring missing for {spec.distro_id}: {spec.keyring}")
        include = f"ca-certificates,{spec.keyring_package}"
        self.runner.run(
            (
                "debootstrap",
                "--arch=amd64",
                "--variant=minbase",
                "--components=main",
                f"--include={include}",
                f"--keyring={spec.keyring}",
                spec.suite,
                str(root),
                spec.mirror,
            )
        )

    def _configure_base(
        self,
        selection: DistroSelection,
        spec: _DistroSpec,
        root_part: PartitionSpec,
        root: Path,
    ) -> None:
        hostname = self.hostname_for(selection)
        self._write(root, "/etc/apt/sources.list", spec.sources, mode="0644")
        self.runner.run(
            (
                "rm",
                "-f",
                "/etc/apt/sources.list.d/ubuntu.sources",
                "/etc/apt/sources.list.d/debian.sources",
            ),
            chroot=root,
        )
        self._write(root, "/etc/hostname", f"{hostname}\n", mode="0644")
        self._write(
            root,
            "/etc/hosts",
            (
                "127.0.0.1 localhost\n"
                f"127.0.1.1 {hostname}\n"
                "::1 localhost ip6-localhost ip6-loopback\n"
                "ff02::1 ip6-allnodes\n"
                "ff02::2 ip6-allrouters\n"
            ),
            mode="0644",
        )
        self._write(root, "/etc/fstab", self._render_fstab(root_part), mode="0644")
        self._mkdir(root, "/boot/efi", mode="0755")
        if any(part.role == "data" for part in self.plan.partitions):
            self._mkdir(root, "/data", mode="0755")

        # Use the live environment's resolver only while packages are installed.
        resolver = "nameserver 1.1.1.1\n"
        if not self.runner.dry_run:
            try:
                resolver = Path("/etc/resolv.conf").read_text(encoding="utf-8")
            except OSError:
                self.log("resolver warning: using temporary 1.1.1.1 fallback")
        self.runner.run(("rm", "-f", "/etc/resolv.conf"), chroot=root)
        self._write(root, "/etc/resolv.conf", resolver, mode="0644")

        self.runner.run(("apt-get", "update"), chroot=root, env=_APT_ENV)

    def _install_packages(
        self,
        selection: DistroSelection,
        spec: _DistroSpec,
        root: Path,
    ) -> None:
        packages = [
            "ca-certificates",
            "dbus",
            "initramfs-tools",
            "keyboard-configuration",
            "locales",
            "network-manager",
            spec.keyring_package,
            spec.kernel_package,
            "tzdata",
        ]
        if self.plan.user.sudo:
            packages.append("sudo")
        if self._ssh_enabled():
            packages.append("openssh-server")
        packages.extend(spec.base_packages)
        packages.extend(
            spec.desktop_packages if selection.variant == "desktop" else spec.server_packages
        )
        packages = sorted(set(packages))
        self.runner.run(
            ("apt-get", "install", "-y", *packages),
            chroot=root,
            env=_APT_ENV,
        )

        locale = self.plan.locale.language
        self._write(root, "/etc/locale.gen", f"{locale} UTF-8\n", mode="0644")
        self.runner.run(("locale-gen", locale), chroot=root, env=_APT_ENV)
        self.runner.run(("update-locale", f"LANG={locale}"), chroot=root, env=_APT_ENV)

        keyboard_layout, keyboard_variant = keyboard_configuration(self.plan.locale.keyboard)
        self._write(
            root,
            "/etc/default/keyboard",
            (
                f'XKBLAYOUT="{keyboard_layout}"\n'
                'XKBMODEL="pc105"\n'
                f'XKBVARIANT="{keyboard_variant}"\n'
                'XKBOPTIONS=""\n'
                'BACKSPACE="guess"\n'
            ),
            mode="0644",
        )
        timezone = self.plan.locale.timezone
        self.runner.run(
            ("ln", "-sfn", f"/usr/share/zoneinfo/{timezone}", "/etc/localtime"),
            chroot=root,
        )
        self._write(root, "/etc/timezone", f"{timezone}\n", mode="0644")
        self.runner.run(
            ("dpkg-reconfigure", "-f", "noninteractive", "tzdata"),
            chroot=root,
            env=_APT_ENV,
        )

        self._write(
            root,
            "/etc/NetworkManager/NetworkManager.conf",
            "[main]\nplugins=keyfile\nno-auto-default=\n",
            mode="0644",
        )
        self.runner.run(("systemctl", "enable", "NetworkManager.service"), chroot=root)
        self.runner.run(
            (
                "systemctl",
                "disable",
                "NetworkManager-wait-online.service",
                "systemd-networkd.service",
                "systemd-networkd-wait-online.service",
            ),
            chroot=root,
            check=False,
            best_effort=True,
        )

    def _configure_account_and_ssh(self, root: Path) -> None:
        username = self.plan.user.username
        self.runner.run(
            (
                "useradd",
                "--create-home",
                "--user-group",
                "--uid",
                "1000",
                "--shell",
                "/bin/bash",
                username,
            ),
            chroot=root,
        )
        if self.plan.user.password_hash:
            self.runner.run(
                ("chpasswd", "--encrypted"),
                chroot=root,
                input_text=f"{username}:{self.plan.user.password_hash}\n",
                sensitive_input=True,
            )
        else:
            self.runner.run(("passwd", "--lock", username), chroot=root)

        if self.plan.user.sudo:
            self.runner.run(("usermod", "--append", "--groups", "sudo", username), chroot=root)
            sudoers = f"{username} ALL=(ALL:ALL) ALL\n"
            sudoers_path = f"/etc/sudoers.d/90-uli-{username}"
            self._write(root, sudoers_path, sudoers, mode="0440")
            self.runner.run(("visudo", "-cf", sudoers_path), chroot=root)

        if not self._ssh_enabled():
            return
        self._write(
            root,
            "/etc/ssh/sshd_config.d/90-uli.conf",
            self._render_sshd_config(),
            mode="0644",
        )
        if self.plan.user.ssh_keys:
            ssh_dir = f"/home/{username}/.ssh"
            self._mkdir(root, ssh_dir, mode="0700")
            keys = "\n".join(self.plan.user.ssh_keys) + "\n"
            self._write(root, f"{ssh_dir}/authorized_keys", keys, mode="0600", sensitive=True)
            self.runner.run(("chown", "-R", f"{username}:{username}", ssh_dir), chroot=root)
        self.runner.run(("systemctl", "enable", "ssh.service"), chroot=root)

    def _configure_kernel(self, selection: DistroSelection, root: Path) -> None:
        hook = render_kernel_symlink_hook(selection.id)
        script_path = "/usr/local/sbin/uli-refresh-kernel-links"
        self._write(root, script_path, hook, mode="0755")
        for hook_path in (
            "/etc/kernel/postinst.d/zz-uli-kernel-links",
            "/etc/initramfs/post-update.d/zz-uli-kernel-links",
        ):
            self._write(root, hook_path, hook, mode="0755")

        swap = next((part for part in self.plan.partitions if part.role == "swap"), None)
        if swap is not None:
            self._write(
                root,
                "/etc/initramfs-tools/conf.d/resume",
                f"RESUME=UUID={swap.uuid}\n",
                mode="0644",
            )
        self.runner.run((script_path,), chroot=root)
        self.runner.run(("update-initramfs", "-u", "-k", "all"), chroot=root)

    def _finalize_system(self, root: Path) -> None:
        self.runner.run(("systemd-machine-id-setup",), chroot=root)
        self.runner.run(("apt-get", "clean"), chroot=root, env=_APT_ENV)
        self.runner.run(("rm", "-f", "/etc/resolv.conf"), chroot=root)
        self.runner.run(
            ("ln", "-s", "../run/NetworkManager/resolv.conf", "/etc/resolv.conf"),
            chroot=root,
        )

    def _verify_system(self, root: Path) -> None:
        """Fail before GRUB installation if a root cannot satisfy its menu entry."""
        for path in ("/etc/fstab", "/etc/hostname", "/etc/default/locale"):
            self.runner.run(("test", "-s", path), chroot=root)
        for path in ("/vmlinuz", "/initrd.img"):
            self.runner.run(("test", "-L", path), chroot=root)
            self.runner.run(("readlink", "-e", path), chroot=root)
            self.runner.run(("test", "-s", path), chroot=root)
        self.runner.run(("getent", "passwd", self.plan.user.username), chroot=root)
        self.runner.run(("systemctl", "is-enabled", "NetworkManager.service"), chroot=root)
        if self._ssh_enabled():
            self.runner.run(("systemctl", "is-enabled", "ssh.service"), chroot=root)

    @contextmanager
    def _package_install_guard(self, root: Path) -> Iterator[None]:
        policy = "#!/bin/sh\nexit 101\n"
        self._write(root, "/usr/sbin/policy-rc.d", policy, mode="0755")
        try:
            yield
        finally:
            self.runner.run(
                ("rm", "-f", "/usr/sbin/policy-rc.d"),
                chroot=root,
                check=False,
                best_effort=True,
            )

    def _render_fstab(self, root: PartitionSpec) -> str:
        lines = [
            "# /etc/fstab generated by Ultimate Linux Installer",
            f"UUID={root.uuid} / {root.filesystem} defaults 0 1",
        ]
        esp = next((part for part in self.plan.partitions if part.role == "esp"), None)
        if esp is not None:
            lines.append(f"UUID={esp.uuid} /boot/efi vfat umask=0077,nofail 0 1")
        swap = next((part for part in self.plan.partitions if part.role == "swap"), None)
        if swap is not None:
            lines.append(f"UUID={swap.uuid} none swap sw 0 0")
        data = next((part for part in self.plan.partitions if part.role == "data"), None)
        if data is not None:
            lines.append(f"UUID={data.uuid} /data {data.filesystem} defaults,nofail 0 2")
        return "\n".join(lines) + "\n"

    def _render_sshd_config(self) -> str:
        password = "no" if self.plan.user.disable_password_auth else "yes"
        return (
            "# Managed by Ultimate Linux Installer\n"
            "PermitRootLogin no\n"
            f"PasswordAuthentication {password}\n"
            f"KbdInteractiveAuthentication {password}\n"
            "PubkeyAuthentication yes\n"
        )

    def _ssh_enabled(self) -> bool:
        return bool(getattr(self.plan.user, "install_ssh_server", False))

    def _prepare_data_partition(self) -> None:
        data = next((part for part in self.plan.partitions if part.role == "data"), None)
        if data is None:
            return
        target = self.mount_root / self.plan.plan_id / "shared-data"
        self._emit("data", 98, "Preparing shared data partition")
        with self.runner.mounted(
            self.partition_device(data),
            target,
            filesystem=data.filesystem,
            options=("--options", "rw"),
        ) as mounted_data:
            # All roots deliberately use UID/GID 1000 for the primary account.
            self.runner.run(("chown", "1000:1000", str(mounted_data)))
            self.runner.run(("chmod", "0770", str(mounted_data)))

    def _mountpoint(self, selection: DistroSelection, index: int) -> Path:
        plan_id = re.sub(r"[^A-Za-z0-9_.-]", "-", self.plan.plan_id)[:64] or "plan"
        name = f"{index + 1:02d}-{selection.id}-{selection.variant}"
        return self.mount_root / plan_id / name

    def _mkdir(self, root: Path, path: str, *, mode: str) -> None:
        _validate_chroot_path(path)
        self.runner.run(("install", "-d", "-m", mode, path), chroot=root)

    def _write(
        self,
        root: Path,
        path: str,
        content: str,
        *,
        mode: str,
        sensitive: bool = False,
    ) -> None:
        _validate_chroot_path(path)
        parent = str(Path(path).parent)
        self.runner.run(("install", "-d", "-m", "0755", parent), chroot=root)
        self.runner.run(
            ("tee", path),
            chroot=root,
            input_text=content,
            sensitive_input=sensitive,
        )
        self.runner.run(("chmod", mode, path), chroot=root)

    def _validate_account_and_locale(self) -> None:
        user = self.plan.user
        if not _SAFE_USER.fullmatch(user.username):
            raise ProvisioningError(f"Unsafe or unsupported username: {user.username!r}")
        if user.username in RESERVED_SYSTEM_USERNAMES:
            raise ProvisioningError(
                f"Username is reserved for a system account: {user.username!r}"
            )
        if user.password_hash:
            if not user.password_hash.startswith(("$", "!")):
                raise ProvisioningError("password_hash must be a crypt-style hash, not plaintext")
            if any(char in user.password_hash for char in ("\n", "\r", "\x00", ":")):
                raise ProvisioningError("password_hash contains an invalid character")
        for key in user.ssh_keys:
            if not key.strip() or any(char in key for char in ("\n", "\r", "\x00")):
                raise ProvisioningError("Each SSH public key must be one non-empty line")
        if user.disable_password_auth and not self._ssh_enabled():
            raise ProvisioningError(
                "disable_password_auth requires install_ssh_server to be enabled"
            )
        if user.disable_password_auth and not user.ssh_keys:
            raise ProvisioningError(
                "At least one SSH public key is required when SSH password login is disabled"
            )
        locale = self.plan.locale
        if not _SAFE_LOCALE.fullmatch(locale.language):
            raise ProvisioningError(f"Unsupported locale syntax: {locale.language!r}")
        keyboard_configuration(locale.keyboard)
        if not is_safe_timezone_name(locale.timezone):
            raise ProvisioningError(f"Unsupported timezone: {locale.timezone!r}")

    def _emit(self, phase: str, percent: int, message: str) -> None:
        self.log(f"{phase}: {message}")
        self.progress(phase, max(0, min(100, percent)), message)


def provision_plan(
    plan: InstallationPlan,
    *,
    dry_run: bool = False,
    runner: CommandRunner | None = None,
    mount_root: str | Path = "/mnt/uli",
    progress: ProgressCallback | None = None,
    log: LogCallback | None = None,
) -> ProvisionResult:
    """Provision every supported root; deliberately does not touch the ESP."""
    command_runner = runner or CommandRunner(dry_run=dry_run, log=log)
    if runner is not None and dry_run != runner.dry_run:
        raise ValueError("dry_run must match the supplied runner")
    return Provisioner(
        plan,
        runner=command_runner,
        mount_root=mount_root,
        progress=progress,
        log=log,
    ).provision_all()


def _spec_for(selection: DistroSelection) -> _DistroSpec:
    if selection.id not in _SPECS:
        raise UnsupportedDistributionError(
            f"Direct provisioning is implemented only for Debian 13 and Ubuntu LTS; "
            f"got {selection.id}:{selection.variant}"
        )
    if selection.variant not in {"desktop", "server"}:
        raise UnsupportedDistributionError(
            f"Unsupported {selection.id} variant: {selection.variant}; expected desktop or server"
        )
    if selection.id != "ubuntu":
        return _SPECS[selection.id]
    return _ubuntu_spec(source_for(selection))


def _ubuntu_spec(source: SourceInfo) -> _DistroSpec:
    """Build the Ubuntu root specification from the session-pinned source."""

    version = source.version.removesuffix(" LTS")
    suite = source.codename
    mirror = source.mirror.rstrip("/")
    keyring = "/usr/share/keyrings/ubuntu-archive-keyring.gpg"
    sources = "\n".join(
        (
            f"deb [signed-by={keyring}] {mirror} {suite} main restricted universe multiverse",
            f"deb [signed-by={keyring}] {mirror} {suite}-updates main restricted universe multiverse",
            f"deb [signed-by={keyring}] {mirror} {suite}-security main restricted universe multiverse",
            "",
        )
    )
    return _DistroSpec(
        distro_id="ubuntu",
        suite=suite,
        version=version,
        mirror=mirror,
        keyring=keyring,
        keyring_package="ubuntu-keyring",
        kernel_package="linux-generic",
        sources=sources,
        base_packages=("linux-firmware",),
        server_packages=("ubuntu-standard",),
        desktop_packages=("ubuntu-standard", "ubuntu-desktop"),
    )


def _validate_release(selection: DistroSelection, spec: _DistroSpec) -> None:
    if not selection.release:
        return
    normalized = selection.release.strip().lower()
    accepted = {spec.suite, spec.version}
    if spec.distro_id == "ubuntu":
        accepted.add(f"{spec.version} lts")
    lts_suffix = r"(?: lts)?" if spec.distro_id == "ubuntu" else ""
    point_release = re.fullmatch(rf"{re.escape(spec.version)}(?:\.\d+)?{lts_suffix}", normalized)
    if normalized not in accepted and point_release is None:
        raise UnsupportedDistributionError(
            f"Unsupported {selection.id} release {selection.release!r}; "
            f"this provisioner targets {spec.version} ({spec.suite})"
        )


def _require_filesystem_uuid(part: PartitionSpec, description: str) -> None:
    if not part.uuid:
        raise ProvisioningError(
            f"Missing filesystem UUID for {description}; refresh UUIDs after mkfs"
        )
    _validate_identifier(part.uuid, f"filesystem UUID for {description}")
    expected = _FAT_UUID if part.filesystem == "fat32" else _GPT_UUID
    if not expected.fullmatch(part.uuid):
        raise ProvisioningError(
            f"Invalid {part.filesystem} filesystem UUID for {description}: {part.uuid!r}"
        )


def _validate_identifier(value: str, description: str) -> None:
    if not _SAFE_ID.fullmatch(value):
        raise ProvisioningError(f"Unsafe {description}: {value!r}")


def _validate_hostname(hostname: str) -> None:
    if not _SAFE_HOSTNAME.fullmatch(hostname):
        raise ProvisioningError(f"Invalid hostname: {hostname!r}")


def _validate_chroot_path(path: str) -> None:
    candidate = Path(path)
    if not candidate.is_absolute() or ".." in candidate.parts or path == "/":
        raise ProvisioningError(f"Unsafe chroot path: {path!r}")


def _between(start: int, end: int, fraction: int) -> int:
    return start + int((end - start) * fraction / 100)
