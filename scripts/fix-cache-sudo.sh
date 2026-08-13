#!/bin/bash
set -euo pipefail
CH=/var/tmp/uli-iso/chroot
ROOT=/root/Linux-Installer/github/Ultimate-Linux-Installer
IMG=/var/tmp/uli-iso/image
WORK=/var/tmp/uli-iso
VERSION=0.2.9
OUT=$ROOT/artifacts/ultimate-linux-installer-${VERSION}-amd64.iso
LABEL=ULI_0_2_9
source "$ROOT/scripts/lib-iso-uefi.sh"

mkdir -p "$CH/etc/sudoers.d" "$CH/var/cache/uli" "$CH/tmp/uli-cache" "$CH/home/uli/.cache/uli"
printf 'uli ALL=(root) NOPASSWD:ALL\n' >"$CH/etc/sudoers.d/uli-installer"
chmod 440 "$CH/etc/sudoers.d/uli-installer"
chown -R 1000:1000 "$CH/var/cache/uli" "$CH/home/uli/.cache" 2>/dev/null || true
chmod 1777 "$CH/var/cache/uli" "$CH/tmp/uli-cache"

rm -rf "$CH/usr/local/lib/python3.10/dist-packages/uli"
cp -a "$ROOT/app/uli" "$CH/usr/local/lib/python3.10/dist-packages/uli"

python3 - <<'PY'
from pathlib import Path
p = Path("/var/tmp/uli-iso/chroot/usr/local/bin/uli-start")
text = p.read_text(encoding="utf-8")
block = (
    "mkdir -p /var/log/uli /home/uli/.mozilla /var/cache/uli /home/uli/.cache/uli /tmp/uli-cache\n"
    "chmod 1777 /var/cache/uli /tmp/uli-cache 2>/dev/null || true\n"
    "chown -R uli:uli /var/cache/uli /home/uli/.cache 2>/dev/null || true"
)
if "chmod 1777 /var/cache/uli" not in text:
    old = "mkdir -p /var/log/uli /home/uli/.mozilla"
    if old in text:
        text = text.replace(old, block, 1)
    else:
        text = text.replace("mkdir -p /var/log/uli", block.split("\n")[0], 1)
        if "chmod 1777 /var/cache/uli" not in text:
            text = text.replace(block.split("\n")[0], block, 1)
    p.write_text(text, encoding="utf-8")
    print("uli-start patched")
else:
    print("uli-start ok")
PY

for m in "$CH/dev/pts" "$CH/dev" "$CH/proc" "$CH/sys"; do umount -l "$m" 2>/dev/null || true; done
rm -f "$IMG/live/filesystem.squashfs" "$ROOT/artifacts"/ultimate-linux-installer-*.iso
mksquashfs "$CH" "$IMG/live/filesystem.squashfs" -comp xz -e boot
GRUB_EFI_DIR="$(uli_find_grub_efi_dir "$CH")"
BOOT_IMG=$WORK/scratch/efi.img
mkdir -p "$WORK/scratch" "$IMG/EFI/BOOT"
uli_make_efi_boot_image "$BOOT_IMG" "$IMG" "$LABEL" "$GRUB_EFI_DIR"
cp "$BOOT_IMG" "$IMG/EFI/BOOT/efiboot.img"
uli_xorriso_hybrid "$OUT" "$LABEL" "$IMG"
ln -sfn "$(basename "$OUT")" "$ROOT/artifacts/ultimate-linux-installer.iso"
ls -lh "$OUT"
echo ISO_READY=$OUT
