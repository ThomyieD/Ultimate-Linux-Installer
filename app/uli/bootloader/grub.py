"""Central GRUB configuration with lessons learned from the Lenovo multiboot project.

Hard requirements encoded here:
- One chef GRUB under EFI/UltimateInstaller (never leave distro GRUB as BootOrder #1)
- Direct linux entries by UUID (no fragile os-prober dependency)
- Stable /vmlinuz and /initrd.img symlinks with relative targets
- Menu timeout visible (never hidden / timeout 0)
- No Advanced submenu clutter
- UEFI Firmware Settings entry last
- Shared swap resume UUID consistent across distros
"""

from __future__ import annotations

import platform
import re
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING
from uuid import UUID

from uli.core.plan import DistroSelection, InstallationPlan, PartitionSpec

if TYPE_CHECKING:
    from uli.install.runner import CommandRecord, CommandRunner


DISTRO_CLASS = {
    "debian": "debian",
    "ubuntu": "ubuntu",
    "fedora": "fedora",
    "arch": "arch",
    "cachyos": "arch",
    "endeavouros": "arch",
    "kali": "kali",
    "mint": "linuxmint",
    "proxmox": "debian",
}

_SAFE_GRUB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
_SAFE_EFI_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_GPT_UUID = re.compile(
    r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
)
_FAT_UUID = re.compile(r"^[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}$")
_EFI_MODULES = (
    "all_video",
    "boot",
    "configfile",
    "echo",
    "efi_gop",
    "efifwsetup",
    "ext2",
    "fat",
    "font",
    "gfxmenu",
    "gfxterm",
    "halt",
    "linux",
    "normal",
    "part_gpt",
    "png",
    "reboot",
    "search",
    "search_fs_uuid",
)
_THEME_FONTS = (
    ("DejaVuSans-12.pf2", "12", Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")),
    ("DejaVuSans-14.pf2", "14", Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")),
    ("DejaVuSans-18.pf2", "18", Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")),
    (
        "DejaVuSans-Bold-20.pf2",
        "20",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ),
)


class GrubInstallError(RuntimeError):
    """Chef-GRUB could not be planned or installed safely."""


class UnsupportedSecureBootError(GrubInstallError):
    """ULI's standalone GRUB is intentionally not advertised as Secure-Boot ready."""


@dataclass(frozen=True)
class GrubInstallResult:
    efi_directory: str
    loader_path: str
    fallback_path: str
    config_path: str
    commands: list[CommandRecord]
    dry_run: bool
    nvram_configured: bool


@dataclass
class MenuEntry:
    title: str
    class_name: str
    root_uuid: str
    kernel: str = "/vmlinuz"
    initrd: str = "/initrd.img"
    options: str = "ro quiet splash"


def _root_for(plan: InstallationPlan, distro: DistroSelection) -> PartitionSpec:
    roots = [
        part
        for part in plan.partitions
        if part.role == "root"
        and part.distribution in {distro.id, f"{distro.id}:{distro.variant}"}
    ]
    exact = [part for part in roots if part.distribution == f"{distro.id}:{distro.variant}"]
    if len(exact) == 1:
        return exact[0]
    matches = [part for part in roots if distro.variant in (part.label or "")]
    if len(matches) == 1:
        return matches[0]
    if len(roots) == 1:
        return roots[0]
    if not roots:
        raise KeyError(f"No root partition for {distro.id}:{distro.variant}")
    raise KeyError(f"Ambiguous root partition for {distro.id}:{distro.variant}")


def _esp_for(plan: InstallationPlan) -> PartitionSpec:
    matches = [part for part in plan.partitions if part.role == "esp"]
    if len(matches) != 1:
        raise GrubInstallError("Exactly one EFI system partition is required")
    if matches[0].filesystem != "fat32":
        raise GrubInstallError("EFI system partition must be FAT32")
    return matches[0]


def _default_entry_index(plan: InstallationPlan) -> int:
    requested = getattr(plan.bootloader, "default_entry", None)
    if not requested:
        return 0
    keys = [f"{selection.id}:{selection.variant}" for selection in plan.distributions]
    if requested not in keys:
        raise GrubInstallError(f"Default GRUB entry is not selected: {requested!r}")
    return keys.index(requested)


def _swap_uuid(plan: InstallationPlan) -> str | None:
    for part in plan.partitions:
        if part.role == "swap" and part.uuid:
            return part.uuid
    return None


def build_menu_entries(
    plan: InstallationPlan,
    *,
    require_uuids: bool = False,
) -> list[MenuEntry]:
    swap = _swap_uuid(plan)
    if swap:
        _validate_grub_identifier(swap, "swap filesystem UUID")
        if require_uuids:
            swap_part = next(
                part for part in plan.partitions if part.role == "swap" and part.uuid == swap
            )
            _validate_partition_filesystem_uuid(swap_part, "swap filesystem UUID")
    entries: list[MenuEntry] = []
    for distro in plan.distributions:
        root = _root_for(plan, distro)
        if require_uuids and not root.uuid:
            raise GrubInstallError(f"Missing root filesystem UUID for {distro.id}:{distro.variant}")
        uuid = root.uuid or f"PENDING-{root.label}"
        if root.uuid:
            _validate_grub_identifier(root.uuid, "root filesystem UUID")
            if require_uuids:
                _validate_partition_filesystem_uuid(root, "root filesystem UUID")
        opts = "ro quiet splash"
        if swap:
            opts += f" resume=UUID={swap}"
        entries.append(
            MenuEntry(
                title=distro.display_name,
                class_name=DISTRO_CLASS.get(distro.id, "linux"),
                root_uuid=uuid,
                options=opts,
            )
        )
    return entries


def render_grub_cfg(
    plan: InstallationPlan,
    *,
    require_uuids: bool = False,
) -> str:
    theme = plan.bootloader.theme
    timeout = plan.bootloader.timeout_seconds
    efi_directory = plan.bootloader.efi_directory
    if not _SAFE_EFI_NAME.fullmatch(theme):
        raise GrubInstallError(f"Unsafe GRUB theme name: {theme!r}")
    if not _SAFE_EFI_NAME.fullmatch(efi_directory):
        raise GrubInstallError(f"Unsafe EFI directory: {efi_directory!r}")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1:
        raise GrubInstallError("GRUB timeout must be visible (at least one second)")
    entries = build_menu_entries(plan, require_uuids=require_uuids)
    default_index = _default_entry_index(plan)
    esp = _esp_for(plan)
    if require_uuids and not esp.uuid:
        raise GrubInstallError("Missing EFI system partition filesystem UUID")
    if esp.uuid:
        _validate_grub_identifier(esp.uuid, "EFI filesystem UUID")
        if require_uuids:
            _validate_partition_filesystem_uuid(esp, "EFI filesystem UUID")

    esp_setup: list[str] = []
    theme_path = f"/boot/grub/themes/{theme}/theme.txt"
    font_paths = ["unicode"]
    if esp.uuid:
        esp_setup = [
            f"search --no-floppy --fs-uuid --set=uli_esp {esp.uuid}",
            f"set prefix=($uli_esp)/EFI/{efi_directory}",
        ]
        theme_path = f"($uli_esp)/EFI/{efi_directory}/themes/{theme}/theme.txt"
        font_paths = [
            f"($uli_esp)/EFI/{efi_directory}/fonts/unicode.pf2",
            *[
                f"($uli_esp)/EFI/{efi_directory}/fonts/{filename}"
                for filename, _size, _source in _THEME_FONTS
            ],
        ]

    header = [
        "# Generated by Ultimate Linux Installer – do not edit by hand",
        *esp_setup,
        f"set timeout={timeout}",
        "set timeout_style=menu",
        f"set default={default_index}",
        "insmod all_video",
        "insmod gfxterm",
        "insmod png",
        *(f"loadfont {font_path}" for font_path in font_paths),
        "set gfxmode=auto",
        "terminal_output gfxterm",
        f"set theme={theme_path}",
        "export theme",
        "",
    ]
    blocks = ["\n".join(header)]

    for entry in entries:
        title = _grub_double_quote(entry.title)
        blocks.append(
            dedent(
                f"""\
                menuentry "{title}" --class {entry.class_name} --class gnu-linux --class gnu --class os {{
                    search --no-floppy --fs-uuid --set=root {entry.root_uuid}
                    linux {entry.kernel} root=UUID={entry.root_uuid} {entry.options}
                    initrd {entry.initrd}
                }}
                """
            )
        )

    blocks.append(
        dedent(
            """\
            menuentry 'UEFI Firmware Settings' --id uefi-firmware {
                fwsetup
            }
            """
        )
    )
    return "\n".join(blocks)


def render_standalone_bootstrap(plan: InstallationPlan) -> str:
    """Small config embedded in the EFI binary; the editable menu stays on ESP."""
    esp = _esp_for(plan)
    if not esp.uuid:
        raise GrubInstallError("Missing EFI system partition filesystem UUID")
    _validate_grub_identifier(esp.uuid, "EFI filesystem UUID")
    _validate_partition_filesystem_uuid(esp, "EFI filesystem UUID")
    efi_directory = plan.bootloader.efi_directory
    if not _SAFE_EFI_NAME.fullmatch(efi_directory):
        raise GrubInstallError(f"Unsafe EFI directory: {efi_directory!r}")
    return dedent(
        f"""\
        # Embedded Ultimate Linux Installer bootstrap
        search --no-floppy --fs-uuid --set=uli_esp {esp.uuid}
        set prefix=($uli_esp)/EFI/{efi_directory}
        configfile ($uli_esp)/EFI/{efi_directory}/grub.cfg
        """
    )


def secure_boot_enabled(
    efivars_root: str | Path = "/sys/firmware/efi/efivars",
    *,
    require_known: bool = False,
) -> bool:
    """Read the UEFI SecureBoot variable without invoking firmware tooling.

    Real installations fail closed when firmware state cannot be established;
    an unsigned standalone loader must never be installed on an assumed-off
    Secure Boot system.
    """
    root = Path(efivars_root)
    if not root.is_dir():
        if require_known:
            raise GrubInstallError("EFI variables are unavailable; Secure Boot state is unknown")
        return False
    expected_name = "secureboot-8be4df61-93ca-11d2-aa0d-00e098032b8c"
    variable = next(
        (candidate for candidate in root.iterdir() if candidate.name.casefold() == expected_name),
        None,
    )
    if variable is not None:
        try:
            payload = variable.read_bytes()
        except OSError as exc:
            raise GrubInstallError(f"Cannot read Secure Boot state from {variable}: {exc}") from exc
        # efivarfs prefixes the one-byte boolean payload with four attribute bytes.
        if len(payload) == 5 and payload[4] in {0, 1}:
            return payload[4] == 1
        raise GrubInstallError(f"Secure Boot variable has an invalid payload: {variable}")
    if require_known:
        raise GrubInstallError("Secure Boot state is unknown (SecureBoot EFI variable missing)")
    return False


def validate_uefi_environment(
    *,
    dry_run: bool = False,
    secure_boot: bool | None = None,
    sys_firmware_root: str | Path = "/sys/firmware/efi",
) -> None:
    """Reject platforms that the amd64 standalone boot path cannot support."""
    if secure_boot is True:
        raise UnsupportedSecureBootError(
            "Secure Boot is enabled; ULI's standalone GRUB is not signed and is unsupported"
        )
    if dry_run:
        return
    machine = platform.machine().lower()
    if machine not in {"x86_64", "amd64"}:
        raise GrubInstallError(f"Chef-GRUB currently supports x86_64 only, got {machine!r}")
    firmware_root = Path(sys_firmware_root)
    if not firmware_root.is_dir():
        raise GrubInstallError(
            "The live system was not booted in UEFI mode (/sys/firmware/efi missing)"
        )
    enabled = (
        secure_boot
        if secure_boot is not None
        else secure_boot_enabled(firmware_root / "efivars", require_known=True)
    )
    if enabled:
        raise UnsupportedSecureBootError(
            "Secure Boot is enabled; disable it before installing ULI's unsigned standalone GRUB"
        )


def validate_chef_grub(
    plan: InstallationPlan,
    *,
    dry_run: bool = False,
    secure_boot: bool | None = None,
    sys_firmware_root: str | Path = "/sys/firmware/efi",
) -> None:
    """Run every non-mutating GRUB preflight, including exact UUID validation."""
    if plan.bootloader.kind != "grub":
        raise GrubInstallError(f"Unsupported central bootloader: {plan.bootloader.kind!r}")
    if not plan.disk.path.startswith("/dev/") or ".." in Path(plan.disk.path).parts:
        raise GrubInstallError(f"Unsafe target disk path: {plan.disk.path!r}")
    unsupported = [
        f"{selection.id}:{selection.variant}"
        for selection in plan.distributions
        if selection.id not in {"debian", "ubuntu"}
        or selection.variant not in {"desktop", "server"}
    ]
    if unsupported:
        raise GrubInstallError(
            "Chef-GRUB install is blocked because these roots are not provisionable: "
            + ", ".join(unsupported)
        )
    plan.require_confirmed()
    render_grub_cfg(plan, require_uuids=True)
    render_standalone_bootstrap(plan)
    validate_uefi_environment(
        dry_run=dry_run,
        secure_boot=secure_boot,
        sys_firmware_root=sys_firmware_root,
    )


def preflight_chef_grub_build(plan: InstallationPlan) -> list[CommandRecord]:
    """Actually build and syntax-check chef GRUB without touching the ESP.

    This preflight is intentionally separate from the final installer so every
    host tool, font and EFI module is exercised before the disk is wiped.
    """
    from uli.install.runner import CommandRunner

    validate_chef_grub(plan, dry_run=True)
    runner = CommandRunner(dry_run=False, use_sudo=False)
    runner.require_tools(("grub-mkfont", "grub-mkstandalone", "grub-script-check"))
    module_root = Path("/usr/lib/grub/x86_64-efi")
    if not module_root.is_dir():
        raise GrubInstallError("GRUB x86_64-efi modules are missing")
    missing_fonts = [
        str(source) for _name, _size, source in _THEME_FONTS if not source.is_file()
    ]
    if missing_fonts:
        raise GrubInstallError("Theme font source(s) missing: " + ", ".join(missing_fonts))
    if not Path("/usr/share/grub/unicode.pf2").is_file():
        raise GrubInstallError("GRUB unicode font is missing")

    cfg = render_grub_cfg(plan, require_uuids=True)
    bootstrap = render_standalone_bootstrap(plan)
    with tempfile.TemporaryDirectory(prefix="uli-grub-preflight-") as workspace_value:
        workspace = Path(workspace_value)
        bootstrap_path = workspace / "bootstrap.cfg"
        config_path = workspace / "grub.cfg"
        standalone_path = workspace / "grubx64.efi"
        bootstrap_path.write_text(bootstrap, encoding="utf-8")
        config_path.write_text(cfg, encoding="utf-8")
        runner.run(("grub-script-check", str(bootstrap_path)))
        runner.run(("grub-script-check", str(config_path)))
        for filename, size, source in _THEME_FONTS:
            runner.run(
                (
                    "grub-mkfont",
                    f"--size={size}",
                    f"--output={workspace / filename}",
                    str(source),
                )
            )
        module_list = " ".join(_EFI_MODULES)
        runner.run(
            (
                "grub-mkstandalone",
                "--format=x86_64-efi",
                f"--output={standalone_path}",
                # Noble GRUB 2.12 cannot safely XZ-compress overlapping module
                # dependencies (it aborts on an already-created .mod file).
                "--compress=none",
                "--locales=",
                "--fonts=unicode",
                "--themes=",
                f"--install-modules={module_list}",
                f"--modules={module_list}",
                f"boot/grub/grub.cfg={bootstrap_path}",
            )
        )
        if not standalone_path.is_file() or standalone_path.stat().st_size < 100_000:
            raise GrubInstallError("GRUB preflight produced no usable x86_64 EFI loader")
    return runner.commands


def install_chef_grub(
    plan: InstallationPlan,
    *,
    runner: CommandRunner | None = None,
    dry_run: bool = False,
    esp_device: str | None = None,
    mount_root: str | Path = "/mnt/uli-esp",
    theme_root: str | Path | None = None,
    progress: Callable[[str, int, str], None] | None = None,
    log: Callable[[str], None] | None = None,
    secure_boot: bool | None = None,
    sys_firmware_root: str | Path = "/sys/firmware/efi",
) -> GrubInstallResult:
    """Install one standalone chef GRUB plus the removable-media fallback.

    This must run only after every root was provisioned and the storage layer
    refreshed real filesystem UUIDs in ``plan.partitions``.
    """
    # Local import avoids a package cycle: uli.install.__init__ imports the job,
    # and the job imports this renderer.
    from uli.install.runner import CommandRunner

    callback = progress or (lambda _phase, _percent, _message: None)
    logger = log or (lambda _message: None)
    command_runner = runner or CommandRunner(dry_run=dry_run, log=logger)
    if runner is not None and runner.dry_run != dry_run:
        raise ValueError("dry_run must match the supplied runner")
    requested_secure_boot = getattr(plan.bootloader, "secure_boot", None)
    if secure_boot is None and isinstance(requested_secure_boot, bool):
        secure_boot = requested_secure_boot
    validate_chef_grub(
        plan,
        dry_run=command_runner.dry_run,
        secure_boot=secure_boot,
        sys_firmware_root=sys_firmware_root,
    )
    command_runner.require_tools(
        ("grub-mkfont", "grub-mkstandalone", "grub-script-check", "mount", "umount")
    )
    if not command_runner.dry_run and not Path("/usr/lib/grub/x86_64-efi").is_dir():
        raise GrubInstallError("GRUB x86_64-efi modules are missing (install grub-efi-amd64-bin)")

    command_offset = len(command_runner.commands)
    esp = _esp_for(plan)
    efi_directory = plan.bootloader.efi_directory
    source_theme = _resolve_theme_root(plan.bootloader.theme, theme_root, command_runner.dry_run)
    source_font = Path("/usr/share/grub/unicode.pf2")
    if not command_runner.dry_run and not source_font.is_file():
        raise GrubInstallError(f"GRUB unicode font missing: {source_font}")
    if not command_runner.dry_run:
        missing_fonts = [
            str(source) for _name, _size, source in _THEME_FONTS if not source.is_file()
        ]
        if missing_fonts:
            raise GrubInstallError("Theme font source(s) missing: " + ", ".join(missing_fonts))

    cfg = render_grub_cfg(plan, require_uuids=True)
    bootstrap = render_standalone_bootstrap(plan)
    device = esp_device or _partition_device(plan, esp)
    esp_mount = Path(mount_root)
    loader_relative = f"EFI/{efi_directory}/grubx64.efi"
    fallback_relative = "EFI/BOOT/BOOTX64.EFI"
    config_relative = f"EFI/{efi_directory}/grub.cfg"
    nvram_configured = False

    callback("bootloader", 2, "Chef-GRUB plan validated")
    if command_runner.dry_run:
        workspace_context = _fixed_workspace(Path("/tmp/uli-grub-plan"))
    else:
        workspace_context = tempfile.TemporaryDirectory(prefix="uli-grub-")

    with workspace_context as workspace_value:
        workspace = Path(workspace_value)
        bootstrap_path = workspace / "bootstrap.cfg"
        config_path = workspace / "grub.cfg"
        standalone_path = workspace / "grubx64.efi"
        if not command_runner.dry_run:
            bootstrap_path.write_text(bootstrap, encoding="utf-8")
            config_path.write_text(cfg, encoding="utf-8")

        callback("bootloader", 10, "Checking GRUB configuration")
        command_runner.run(("grub-script-check", str(bootstrap_path)))
        command_runner.run(("grub-script-check", str(config_path)))

        callback("bootloader", 25, "Building standalone GRUB EFI image")
        generated_fonts: list[Path] = []
        for filename, size, source in _THEME_FONTS:
            destination = workspace / filename
            command_runner.run(
                (
                    "grub-mkfont",
                    f"--size={size}",
                    f"--output={destination}",
                    str(source),
                )
            )
            generated_fonts.append(destination)
        module_list = " ".join(_EFI_MODULES)
        command_runner.run(
            (
                "grub-mkstandalone",
                "--format=x86_64-efi",
                f"--output={standalone_path}",
                "--compress=none",
                "--locales=",
                "--fonts=unicode",
                "--themes=",
                f"--install-modules={module_list}",
                f"--modules={module_list}",
                f"boot/grub/grub.cfg={bootstrap_path}",
            )
        )

        callback("bootloader", 50, "Mounting EFI system partition")
        with command_runner.mounted(device, esp_mount, filesystem="vfat") as mounted_esp:
            chef_dir = mounted_esp / "EFI" / efi_directory
            fallback_dir = mounted_esp / "EFI" / "BOOT"
            theme_target = chef_dir / "themes" / plan.bootloader.theme
            font_target = chef_dir / "fonts"
            command_runner.run(
                (
                    "install",
                    "-d",
                    "-m",
                    "0755",
                    str(chef_dir),
                    str(fallback_dir),
                    str(theme_target),
                    str(font_target),
                )
            )
            command_runner.run(
                ("install", "-m", "0644", str(config_path), str(chef_dir / "grub.cfg"))
            )
            command_runner.run(("cp", "-a", f"{source_theme}/.", str(theme_target)))
            command_runner.run(
                ("install", "-m", "0644", str(source_font), str(font_target / "unicode.pf2"))
            )
            for generated_font in generated_fonts:
                command_runner.run(
                    (
                        "install",
                        "-m",
                        "0644",
                        str(generated_font),
                        str(font_target / generated_font.name),
                    )
                )
            command_runner.run(
                ("install", "-m", "0644", str(standalone_path), str(chef_dir / "grubx64.efi"))
            )
            # The fallback is intentionally the same standalone binary, so a
            # wiped NVRAM still boots via the removable-media path.
            command_runner.run(
                ("install", "-m", "0644", str(standalone_path), str(fallback_dir / "BOOTX64.EFI"))
            )
            command_runner.run(("sync", "-f", str(mounted_esp)))

        callback("bootloader", 85, "Creating UltimateInstaller firmware entry")
        nvram_configured = _configure_nvram_best_effort(
            plan,
            command_runner,
            efi_directory=efi_directory,
            log=logger,
            sys_firmware_root=Path(sys_firmware_root),
        )

    callback("bootloader", 100, "Chef-GRUB installed")
    return GrubInstallResult(
        efi_directory=efi_directory,
        loader_path=loader_relative,
        fallback_path=fallback_relative,
        config_path=config_relative,
        commands=command_runner.commands_since(command_offset),
        dry_run=command_runner.dry_run,
        nvram_configured=nvram_configured,
    )


def plan_chef_grub_commands(
    plan: InstallationPlan,
    *,
    esp_device: str | None = None,
    mount_root: str | Path = "/mnt/uli-esp",
    theme_root: str | Path | None = None,
    use_sudo: bool = False,
) -> list[CommandRecord]:
    """Return the exact standalone-GRUB argv plan without touching the host."""
    from uli.install.runner import CommandRunner

    runner = CommandRunner(dry_run=True, use_sudo=use_sudo)
    return install_chef_grub(
        plan,
        runner=runner,
        dry_run=True,
        esp_device=esp_device,
        mount_root=mount_root,
        theme_root=theme_root,
    ).commands


def _configure_nvram_best_effort(
    plan: InstallationPlan,
    runner: CommandRunner,
    *,
    efi_directory: str,
    log: Callable[[str], None],
    sys_firmware_root: Path,
) -> bool:
    part_number = plan.partitions.index(_esp_for(plan)) + 1
    esp_partuuid = _esp_for(plan).partuuid
    if not esp_partuuid:
        raise GrubInstallError("EFI partition has no PARTUUID for NVRAM verification")
    loader = rf"\EFI\{efi_directory}\grubx64.efi"
    create_argv = (
        "efibootmgr",
        "--create",
        "--disk",
        plan.disk.path,
        "--part",
        str(part_number),
        "--label",
        "UltimateInstaller",
        "--loader",
        loader,
    )
    if runner.dry_run:
        runner.run(create_argv, check=False, best_effort=True)
        return False
    if shutil.which("efibootmgr") is None:
        log("bootloader warning: efibootmgr is unavailable; fallback EFI loader is installed")
        return False
    if not (sys_firmware_root / "efivars").is_dir():
        log("bootloader warning: EFI variables unavailable; fallback EFI loader is installed")
        return False

    query = runner.run(("efibootmgr", "-v"), check=False, best_effort=True)
    if query.returncode != 0:
        log(
            f"bootloader warning: efibootmgr query failed: {(query.stderr or query.stdout).strip()}"
        )
        return False
    boot_number = _find_chef_boot_number(
        query.stdout,
        efi_directory,
        esp_partuuid=esp_partuuid,
        part_number=part_number,
    )
    if boot_number is None:
        created = runner.run(create_argv, check=False, best_effort=True)
        if created.returncode != 0:
            log(
                "bootloader warning: could not create NVRAM entry; "
                "the EFI/BOOT fallback remains bootable"
            )
            return False
        query = runner.run(("efibootmgr", "-v"), check=False, best_effort=True)
        if query.returncode != 0:
            return False
        boot_number = _find_chef_boot_number(
            query.stdout,
            efi_directory,
            esp_partuuid=esp_partuuid,
            part_number=part_number,
        )
    if boot_number is None:
        log("bootloader warning: created firmware entry could not be identified")
        return False

    order = _parse_boot_order(query.stdout)
    if not order:
        log("bootloader warning: firmware returned no BootOrder")
        return False
    if order[0] != boot_number:
        reordered = [boot_number, *(item for item in order if item != boot_number)]
        changed = runner.run(
            ("efibootmgr", "--bootorder", ",".join(reordered)),
            check=False,
            best_effort=True,
        )
        if changed.returncode != 0:
            log("bootloader warning: firmware entry exists but BootOrder could not be changed")
            return False
        verified = runner.run(("efibootmgr", "-v"), check=False, best_effort=True)
        if verified.returncode != 0:
            return False
        verified_number = _find_chef_boot_number(
            verified.stdout,
            efi_directory,
            esp_partuuid=esp_partuuid,
            part_number=part_number,
        )
        verified_order = _parse_boot_order(verified.stdout)
        if verified_number != boot_number or not verified_order or verified_order[0] != boot_number:
            log("bootloader warning: firmware did not retain the requested BootOrder")
            return False
    return True


def _find_chef_boot_number(
    output: str,
    efi_directory: str,
    *,
    esp_partuuid: str,
    part_number: int,
) -> str | None:
    expected_partuuid = str(UUID(esp_partuuid))
    expected_loader = _normalize_efi_file_path(
        rf"\EFI\{efi_directory}\grubx64.efi"
    )
    for line in output.splitlines():
        entry = re.fullmatch(
            r"Boot([0-9A-Fa-f]{4})\*\s+UltimateInstaller\s+(\S.*)",
            line,
        )
        if entry is None:
            continue

        device_path = entry.group(2)
        partition = re.search(
            r"(?:^|/)HD\(\s*([0-9]+)\s*,\s*GPT\s*,\s*"
            r"([0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12})\s*,[^)]*\)"
            r"(?:/|$)",
            device_path,
            flags=re.IGNORECASE,
        )
        loader = re.search(r"(?:^|/)File\(([^)]*)\)$", device_path, flags=re.IGNORECASE)
        if partition is None or loader is None:
            continue
        if _normalize_efi_file_path(loader.group(1)) != expected_loader:
            continue
        try:
            found_partuuid = str(UUID(partition.group(2)))
        except ValueError:
            continue
        if int(partition.group(1)) == part_number and found_partuuid == expected_partuuid:
            return entry.group(1).upper()
    return None


def _normalize_efi_file_path(path: str) -> str:
    normalized = re.sub(r"[\\/]+", r"\\", path.strip())
    return normalized.casefold()


def _parse_boot_order(output: str) -> list[str]:
    for line in output.splitlines():
        if line.startswith("BootOrder:"):
            return [
                item.strip().upper() for item in line.partition(":")[2].split(",") if item.strip()
            ]
    return []


def _partition_device(plan: InstallationPlan, part: PartitionSpec) -> str:
    if part.partuuid:
        _validate_grub_identifier(part.partuuid, "EFI PARTUUID")
        return f"/dev/disk/by-partuuid/{part.partuuid}"
    try:
        index = plan.partitions.index(part) + 1
    except ValueError as exc:
        raise GrubInstallError("EFI partition does not belong to this plan") from exc
    separator = (
        "p" if any(token in plan.disk.path for token in ("nvme", "mmcblk", "loop", "md")) else ""
    )
    return f"{plan.disk.path}{separator}{index}"


def _resolve_theme_root(
    theme: str,
    supplied: str | Path | None,
    dry_run: bool,
) -> Path:
    if not _SAFE_EFI_NAME.fullmatch(theme):
        raise GrubInstallError(f"Unsafe GRUB theme name: {theme!r}")
    if supplied is not None:
        base = Path(supplied)
        candidate = base if base.name == theme else base / theme
        if dry_run or (candidate / "theme.txt").is_file():
            return candidate
        raise GrubInstallError(f"GRUB theme not found: {candidate / 'theme.txt'}")

    here = Path(__file__).resolve()
    candidates = (
        here.parents[3] / "themes" / "grub" / theme,
        Path("/usr/local/share/uli/themes/grub") / theme,
        Path("/usr/local/share/uli/themes") / theme,
        Path("/usr/share/uli/themes/grub") / theme,
        Path("/usr/share/uli/themes") / theme,
        Path("/opt/uli/themes/grub") / theme,
        Path("/opt/uli/src/themes/grub") / theme,
    )
    existing = next(
        (candidate for candidate in candidates if (candidate / "theme.txt").is_file()), None
    )
    if existing is not None:
        return existing
    if dry_run:
        return candidates[0]
    raise GrubInstallError(f"GRUB theme {theme!r} was not installed on the live system")


class _fixed_workspace:
    """Dry-run equivalent of TemporaryDirectory with a stable, non-created path."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def __enter__(self) -> str:
        return str(self.path)

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        return None


def _validate_grub_identifier(value: str, description: str) -> None:
    if not _SAFE_GRUB_ID.fullmatch(value):
        raise GrubInstallError(f"Unsafe {description}: {value!r}")


def _validate_partition_filesystem_uuid(part: PartitionSpec, description: str) -> None:
    if not part.uuid:
        raise GrubInstallError(f"Missing {description}")
    expected = _FAT_UUID if part.filesystem == "fat32" else _GPT_UUID
    if not expected.fullmatch(part.uuid):
        raise GrubInstallError(f"Invalid {part.filesystem} {description}: {part.uuid!r}")


def _grub_double_quote(value: str) -> str:
    if any(char in value for char in ("\n", "\r", "\x00")):
        raise GrubInstallError("GRUB menu titles must be a single line")
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$")


def render_kernel_symlink_hook(distro_id: str) -> str:
    """Hook installed into each distro so kernel updates refresh stable root symlinks."""
    if distro_id in {"arch", "cachyos", "endeavouros"}:
        kernel_glob = "vmlinuz-linux*"
        initrd_glob = "initramfs-linux*.img"
        script = dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            # Ultimate Linux Installer – keep /vmlinuz and /initrd.img stable (relative links)
            boot=/boot
            k=$(ls -1 ${{boot}}/{kernel_glob} 2>/dev/null | sort -V | tail -n1 || true)
            i=$(ls -1 ${{boot}}/{initrd_glob} 2>/dev/null | sort -V | tail -n1 || true)
            [[ -n "$k" && -n "$i" ]] || exit 0
            ln -sfr "$k" /vmlinuz
            ln -sfr "$i" /initrd.img
            """
        )
    else:
        script = dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            # Ultimate Linux Installer – keep /vmlinuz and /initrd.img stable (relative links)
            k=$(ls -1 /boot/vmlinuz-* 2>/dev/null | sort -V | tail -n1 || true)
            i=$(ls -1 /boot/initrd.img-* /boot/initramfs-*.img 2>/dev/null | sort -V | tail -n1 || true)
            [[ -n "$k" && -n "$i" ]] || exit 0
            ln -sfr "$k" /vmlinuz
            ln -sfr "$i" /initrd.img
            """
        )
    return script


def render_efi_bootorder_fix() -> str:
    """Ensure UltimateInstaller remains BootOrder #1 after distro installers meddle."""
    return dedent(
        """\
        #!/usr/bin/env bash
        set -euo pipefail
        # Ultimate Linux Installer – reclaim chef GRUB boot order
        if ! command -v efibootmgr >/dev/null; then
          exit 0
        fi
        mapfile -t entries < <(efibootmgr | sed -n 's/^Boot\\([0-9A-F]*\\).*UltimateInstaller.*/\\1/p')
        if [[ ${#entries[@]} -eq 0 ]]; then
          echo "UltimateInstaller EFI entry not found" >&2
          exit 1
        fi
        chef="${entries[0]}"
        current=$(efibootmgr | sed -n 's/^BootOrder: //p')
        rest=$(echo "$current" | tr ',' '\\n' | grep -vx "$chef" | paste -sd, -)
        if [[ -n "$rest" ]]; then
          efibootmgr -o "${chef},${rest}" >/dev/null
        else
          efibootmgr -o "${chef}" >/dev/null
        fi
        """
    )


def render_fstab_swap_guard(swap_uuid: str) -> str:
    """Prevent slow boot from stale resume UUID (a real failure mode from the laptop project)."""
    return dedent(
        f"""\
        # Ultimate Linux Installer – align resume with shared swap
        mkdir -p /etc/initramfs-tools/conf.d
        echo 'RESUME=UUID={swap_uuid}' > /etc/initramfs-tools/conf.d/resume
        if [[ -f /etc/default/grub ]]; then
          sed -i 's/^GRUB_CMDLINE_LINUX_DEFAULT=.*/GRUB_CMDLINE_LINUX_DEFAULT="quiet splash resume=UUID={swap_uuid}"/' /etc/default/grub || true
        fi
        """
    )


def render_sudo_user_guard(username: str) -> str:
    """Ensure the created user can sudo (Debian pitfall when a root password was set)."""
    return dedent(
        f"""\
        # Ultimate Linux Installer – guarantee sudo for the primary user
        if getent passwd {username} >/dev/null; then
          usermod -aG sudo {username} 2>/dev/null || usermod -aG wheel {username} 2>/dev/null || true
          mkdir -p /etc/sudoers.d
          echo '{username} ALL=(ALL:ALL) ALL' > /etc/sudoers.d/90-uli-{username}
          chmod 440 /etc/sudoers.d/90-uli-{username}
        fi
        """
    )
