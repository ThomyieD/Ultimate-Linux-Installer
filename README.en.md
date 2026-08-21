# Ultimate Linux Installer

Ultimate Linux Installer (ULI) is a graphical installer for either one Linux system or a controlled Linux multiboot setup on an entire disk.

Boot from USB → full-screen web kiosk → review and explicitly confirm the installation plan → provision systems directly from official package repositories → boot them through one central GRUB menu.

> **German is the default UI language.** English can be selected in the installer.
> Deutsche Dokumentation: [README.md](README.md)

## Released v0.3 scope

v0.3 deliberately limits the executable installation path:

- **Platform:** x86_64 systems booted in UEFI mode, with Secure Boot disabled
- **Target:** one disk that may be erased in full; GPT, one shared EFI System Partition, and ext4 root partitions
- **Modes:** simple installation with exactly one system, or multiboot with at least two systems
- **Released systems:** Debian 13 and Ubuntu 24.04 LTS, each in desktop or server form
- **Provisioning:** direct `debootstrap`/APT installation from official Debian and Ubuntu repositories; distro ISOs are not bundled on the installer stick
- **Source verification:** the OpenPGP-signed `InRelease` metadata is verified before the first destructive operation; APT/debootstrap then verifies packages against the signed metadata
- **UI:** the primary interface is a full-screen, nine-step web kiosk: network, mode, distributions, sources, settings, storage, review, installation, and completion
- **Storage:** equal or individual root sizing, with optional swap and data partitions
- **Bootloader:** one central GRUB under `EFI/UltimateInstaller`, generated only after formatting with real UUIDs/PARTUUIDs, plus an `EFI/BOOT` fallback

Fedora, Arch Linux, Proxmox VE, **Add distribution**, and **Remove distribution** remain visible as planned product scope, but are technically disabled in v0.3. This prevents unfinished paths from modifying data. Proxmox is intended to remain simple-install only.

## Safety model

The browser cannot submit a device path or disk size. It selects only a disk ID returned by the privileged backend. The backend validates the settings and minimum sizes, binds the complete preview to a SHA-256 plan fingerprint and the current disk identity, and issues a short-lived one-time token only after explicit approval. Token, revision, and disk identity are checked again at installation start. Signed source metadata and UEFI/Secure-Boot prerequisites are checked before wiping.

Passwords are hashed when submitted and are not returned by the public state API or written in clear text to the audit record. The live image runs the privileged backend as a dedicated service; the kiosk user does not receive blanket `sudo` access.

## Download an ISO

Installer images do not belong in Git history. Published images and checksums are available from **[GitHub Releases](https://github.com/ThomyieD/Ultimate-Linux-Installer/releases)**. Locally generated test images live under `artifacts/` and are not committed.

Download `ultimate-linux-installer-<version>-amd64.iso` and `SHA256SUMS`, verify the checksum, then write the ISO to USB with Rufus, balenaEtcher, or `dd` and boot it in UEFI mode. If no suitable release asset exists yet, build the image locally.

## Development and tests

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Safe desktop simulation of the primary web UI
uli --dry-run --simulate-disk --lang en

# Automated tests and static checks
pytest
ruff check app adapters tests
```

The web UI is then available at `http://127.0.0.1:8787`. The earlier PySide6 UI is available only as a non-destructive development simulation through `uli --ui qt --dry-run`; real installations run exclusively through the web kiosk.

### Build the ISO locally

On an Ubuntu/Debian build host, install the required debootstrap, xorriso, squashfs, GRUB, OVMF, and QEMU tools. The canonical entry point is:

```bash
./scripts/generate-theme-assets.sh
sudo scripts/build-iso.sh
sudo scripts/verify-iso-uefi.sh artifacts/ultimate-linux-installer-0.3.0-amd64.iso
./scripts/run-qemu.sh
```

Versioned output is placed under `artifacts/`. The manually dispatched GitHub workflow runs tests and builds an artifact; it attaches files to a GitHub Release only when a release tag is explicitly supplied.

## Current acceptance status

The v0.3 codebase contains the end-to-end orchestration path for preview/confirmation, partitioning, signed sources, Debian/Ubuntu provisioning, and chef GRUB. Unit, API, dry-run, and ISO-structure checks cover the main planning and safety boundaries.

The following are **not yet accepted as complete**:

- destructive end-to-end installation on real hardware for all four released variants,
- broad hardware coverage for Wi-Fi, graphics, firmware, and storage devices,
- Secure Boot support,
- Fedora, Arch, and Proxmox installation,
- safe resizing of existing installations for add/remove,
- reliable resume behavior across every possible power-loss point.

Until that acceptance work is complete, test v0.3 on expendable hardware or in a VM with a disposable disk. **A real installation erases the selected target disk in full.**

Architecture details are in [docs/architecture/overview.md](docs/architecture/overview.md). The original product specifications and mockups remain under `docs/reference/`.

## License

MIT – see [LICENSE](LICENSE).
