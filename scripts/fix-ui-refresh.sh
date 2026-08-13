#!/bin/bash
# UI refresh fix + adapters packaging. Keeps only the newest ISO.
set -euo pipefail
ROOT=/root/Linux-Installer/github/Ultimate-Linux-Installer
CH=/var/tmp/uli-iso/chroot
WORK=/var/tmp/uli-iso
IMG=$WORK/image
VERSION=0.2.4
OUT_ISO=$ROOT/artifacts/ultimate-linux-installer-${VERSION}-amd64.iso
LABEL=ULI_0_2_4
PYSITE=$CH/usr/local/lib/python3.10/dist-packages

source "$ROOT/scripts/lib-iso-uefi.sh"

echo "[1] sync app + adapters..."
mkdir -p "$PYSITE"
rm -rf "$PYSITE/uli" "$PYSITE/adapters"
cp -a "$ROOT/app/uli" "$PYSITE/uli"
cp -a "$ROOT/adapters" "$PYSITE/adapters"

# Smoke-check catalog import inside chroot paths
PYTHONPATH="$PYSITE" python3 - <<'PY'
import sys
sys.path.insert(0, "/var/tmp/uli-iso/chroot/usr/local/lib/python3.10/dist-packages")
from uli.core.catalog import catalog_for_mode
items = catalog_for_mode("simple")
assert items, "catalog empty"
print(f"catalog_ok={len(items)}")
PY

echo "[2] ensure mountpoints + unmount..."
for m in "$CH/dev/pts" "$CH/dev" "$CH/proc" "$CH/sys" "$CH/run"; do
  while mountpoint -q "$m" 2>/dev/null; do
    umount -l "$m" || break
    sleep 0.2
  done
done
if mount | grep -q "$CH/"; then
  echo "ERROR: mounts still present under chroot:" >&2
  mount | grep "$CH/" >&2
  exit 1
fi
mkdir -p "$CH/proc" "$CH/sys" "$CH/dev" "$CH/run/lock" "$CH/tmp" "$CH/boot"
chmod 1777 "$CH/tmp"

# Keep existing uli-start / NM / vmtools from 0.2.3; only refresh GRUB configs if missing
mkdir -p "$IMG/boot/grub" "$IMG/isolinux" "$IMG/EFI/BOOT" "$WORK/scratch"
cat >"$IMG/boot/grub/grub.cfg" <<'EOF'
set timeout=0
set timeout_style=hidden
set default=0
insmod all_video
insmod linux
insmod linuxefi
menuentry "Ultimate Linux Installer" {
    linux /live/vmlinuz boot=live components quiet splash hostname=uli-live username=uli console=tty0
    initrd /live/initrd.img
}
EOF
cat >"$IMG/isolinux/isolinux.cfg" <<'EOF'
UI menu.c32
PROMPT 0
TIMEOUT 1
DEFAULT uli
LABEL uli
  MENU LABEL Ultimate Linux Installer
  KERNEL /live/vmlinuz
  APPEND initrd=/live/initrd.img boot=live components quiet splash hostname=uli-live username=uli
EOF

echo "[3] squash + ISO (remove previous ISOs)..."
rm -f "$IMG/live/filesystem.squashfs"
rm -f "$ROOT/artifacts"/ultimate-linux-installer-*.iso
rm -f "$ROOT/artifacts"/ultimate-linux-installer.iso
mksquashfs "$CH" "$IMG/live/filesystem.squashfs" -comp xz -e boot
GRUB_EFI_DIR="$(uli_find_grub_efi_dir "$CH")"
BOOT_IMG=$WORK/scratch/efi.img
uli_make_efi_boot_image "$BOOT_IMG" "$IMG" "$LABEL" "$GRUB_EFI_DIR"
cp "$BOOT_IMG" "$IMG/EFI/BOOT/efiboot.img"
uli_xorriso_hybrid "$OUT_ISO" "$LABEL" "$IMG"
ln -sfn "$(basename "$OUT_ISO")" "$ROOT/artifacts/ultimate-linux-installer.iso"
ls -lh "$OUT_ISO"
echo "ISO_READY=$OUT_ISO"
