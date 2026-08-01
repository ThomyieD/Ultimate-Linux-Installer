# Ultimate Linux Installer

Modern, dark-themed UEFI installer for single-disk and multiboot Linux setups.

Boot from USB → graphical installer (not a manual live-desktop workflow) → download from official mirrors → unattended install → central GRUB menu in the style of the target boot screen.

> **German is the default UI language.** English can be selected in the installer.  
> Deutsche Dokumentation: [README.md](README.md)

## Download a ready ISO

**Distro ISOs are not on the stick** — they are downloaded from official mirrors during installation. The installer ISO is therefore much smaller than a “bundle every distro” USB.

It still ships a **full bootable live environment** (kernel, firmware, networking, disk tools, Qt UI), typically a few hundred MB up to ~1–2 GB. That is too large / impractical for Git, so the ISO is published under **[Releases](https://github.com/ThomyieD/Ultimate-Linux-Installer/releases)** instead.

## Features (MVP)

- **Modes:** Simple · Multiboot · Add distribution · Remove distribution
- **Distros:** Debian, Ubuntu (Desktop/Server), Fedora (Workstation/Server), Arch, Proxmox VE (simple only)
- **UI:** Dark modern Qt UI, German default, English toggle
- **Storage:** Even split or planned layouts; installation USB never offered as target
- **Bootloader:** One chef GRUB (`EFI/UltimateInstaller`) with themed menu
- Safety nets from the real multiboot project (BootOrder reclaim, kernel symlink hooks, shared swap resume, sudo guarantee, resumable state)

## Architecture

See [docs/architecture/overview.md](docs/architecture/overview.md).

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uli --dry-run --lang de
pytest
```

### Build bootable ISO (developers)

```bash
sudo apt install live-build qemu-system-x86 ovmf xorriso squashfs-tools
./scripts/generate-theme-assets.sh
./scripts/build-iso.sh
./scripts/run-qemu.sh
```

Output: `artifacts/ultimate-linux-installer.iso` — publish via GitHub Releases, do not commit.

## License

MIT – see [LICENSE](LICENSE).
