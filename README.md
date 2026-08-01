# Ultimate Linux Installer

Modern, dark-themed UEFI installer for single-disk and multiboot Linux setups.

Boot from USB → graphical installer (not a manual live-desktop workflow) → download from official mirrors → unattended install → central GRUB menu in the style of the target boot screen.

## Features (MVP)

- **Modes:** Simple · Multiboot · Add distribution · Remove distribution
- **Distros:** Debian, Ubuntu (Desktop/Server), Fedora (Workstation/Server), Arch, Proxmox VE (simple only)
- **UI:** Dark modern Qt UI, German default, English toggle
- **Storage:** Even split or planned layouts, ESP + roots + optional swap/data; installation USB never offered as target
- **Bootloader:** One chef GRUB (`EFI/UltimateInstaller`) with themed menu; UEFI Firmware Settings last
- **Safety nets** from real multiboot pain points:
  - reclaim UEFI BootOrder after distro installers
  - stable `/vmlinuz` + `/initrd.img` relative symlinks + update hooks
  - shared swap `resume=UUID=…` aligned across systems
  - ensure primary user is in `sudo`/`wheel`
  - disable wait-online delays where appropriate
  - resumable install state machine

## Architecture

```text
UEFI firmware
  → USB bootloader
  → minimal Linux live system
  → Ultimate Linux Installer (PySide6)
       ├── network / storage / downloads
       ├── distro adapters (preseed / autoinstall / kickstart / pacstrap)
       └── central GRUB + themes
```

Details: [docs/architecture/overview.md](docs/architecture/overview.md)

## Development

### On Linux (recommended: Debian/Ubuntu build host)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uli --dry-run --lang de          # desktop UI against simulated disks
pytest
```

### Build bootable ISO (Linux host with live-build)

```bash
sudo apt install live-build qemu-system-x86 ovmf xorriso squashfs-tools
./scripts/generate-theme-assets.sh
./scripts/build-iso.sh
./scripts/run-qemu.sh
```

> Destructive partitioning runs only inside the live image with confirmation. Desktop mode is dry-run by default.

## Repository layout

```text
app/uli/           # Python application (UI + core)
adapters/          # Per-distribution automation adapters
themes/grub/       # GRUB themes (uli-lenovo, uli-dark)
live-build/        # Debian live-build configuration
schemas/           # Installation plan JSON schema
scripts/           # ISO + QEMU helpers
tests/             # Unit / integration / QEMU harnesses
docs/              # Architecture + reference mockups
```

## Status

**0.1.0 – foundation MVP**

Working today: wizard UI, plan generation, adapters, GRUB rendering, dry-run partitioning commands, state machine, tests.

Next: live ISO polish, real download+verify pipeline, full multi-install orchestration against QEMU, then hardware validation.

## License

MIT – see [LICENSE](LICENSE).
