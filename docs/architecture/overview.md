# Architecture overview

## Goals

- Universal x86_64 UEFI installer (not tied to one laptop)
- Looks and feels like a product installer, not a live desktop with scripts
- Stable multiboot result matching the themed GRUB target look
- Resumable, adapter-based automation per distro family

## Boot chain

1. Firmware starts the USB stick (GRUB/shim)
2. Minimal Debian live environment boots
3. Autostart launches `uli` fullscreen dark UI
4. User completes wizard; confirmed plan is persisted
5. Orchestrator partitions (once), installs each distro via its adapter
6. After each distro installer, BootOrder is reclaimed to `UltimateInstaller`
7. Finalization writes central `grub.cfg`, themes, kernel symlink hooks, sudo/swap guards
8. Reboot into themed menu

## Installation modes

| Mode | Behavior |
|------|----------|
| Simple | One distro; wipe disk; official unattended path preferred |
| Multiboot | Several roots + shared ESP; controlled/hybrid install |
| Add | Detect existing ULI layout; carve space; install one more |
| Remove | Drop a root, grow neighbors/data, refresh GRUB |

Proxmox is **simple-only** (no multiboot conversion).

## Adapters

Each adapter provides:

- `resolve_release()` – newest *supported* release metadata + checksums
- `generate_automation()` – preseed / autoinstall / kickstart / pacstrap assets
- `post_install_hooks()` – chroot snippets for ULI guarantees

## Lessons encoded from the Lenovo multiboot project

| Failure mode | ULI mitigation |
|--------------|----------------|
| Distro GRUB becomes chef / hidden menu | Central GRUB + BootOrder reclaim script |
| Missing / wrong menu entries | Direct UUID linux entries, no os-prober dependency |
| Broken Arch/CachyOS kernel paths | Relative `ln -sfr` hooks to `/vmlinuz` & `/initrd.img` |
| Slow boots (stale resume UUID) | Shared swap UUID written into resume configs |
| Debian user without sudo | Explicit sudoers drop-in |
| USB selected as target | Installation medium detection + exclusion |
| Power loss mid-install | JSON state machine with resume |

## Safety

```python
if not installation_plan.confirmed:
    raise RuntimeError("Destructive storage operation was not confirmed")
```

Dry-run is default outside the live image. QEMU tests use throwaway `qcow2` disks only.
