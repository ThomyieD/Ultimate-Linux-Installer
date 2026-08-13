#!/usr/bin/env bash
# Rebuild only bootloaders + hybrid ISO from an existing /var/tmp/uli-iso tree.
# Use after fixing UEFI without a full debootstrap.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${ULI_ISO_WORK:-/var/tmp/uli-iso}"
CHROOT="$WORK/chroot"
IMG="$WORK/image"
VERSION="${ULI_VERSION:-0.1.1}"
OUT_DIR="$ROOT/artifacts"
OUT_ISO="$OUT_DIR/ultimate-linux-installer-${VERSION}-amd64.iso"
LABEL="ULI_${VERSION//./_}"

# shellcheck source=lib-iso-uefi.sh
source "$ROOT/scripts/lib-iso-uefi.sh"

[ -f "$IMG/live/filesystem.squashfs" ] || {
  echo "ERROR: missing $IMG/live/filesystem.squashfs — run build-iso-simple.sh first" >&2
  exit 1
}
[ -f "$IMG/live/vmlinuz" ] || {
  echo "ERROR: missing kernel in $IMG/live" >&2
  exit 1
}

echo "[1/3] isolinux + grub.cfg..."
mkdir -p "$IMG/isolinux" "$IMG/boot/grub" "$IMG/EFI/BOOT" "$WORK/scratch"
if [ ! -f "$IMG/isolinux/isolinux.bin" ]; then
  if [ -f /usr/lib/ISOLINUX/isolinux.bin ]; then
    cp /usr/lib/ISOLINUX/isolinux.bin "$IMG/isolinux/"
    cp /usr/lib/syslinux/modules/bios/*.c32 "$IMG/isolinux/" 2>/dev/null || true
  elif [ -f "$CHROOT/usr/lib/ISOLINUX/isolinux.bin" ]; then
    cp "$CHROOT/usr/lib/ISOLINUX/isolinux.bin" "$IMG/isolinux/"
    cp "$CHROOT/usr/lib/syslinux/modules/bios/"*.c32 "$IMG/isolinux/" 2>/dev/null || true
  else
    echo "ERROR: isolinux.bin not found" >&2
    exit 1
  fi
fi
cat >"$IMG/isolinux/isolinux.cfg" <<'EOF'
UI menu.c32
PROMPT 0
TIMEOUT 30
DEFAULT uli
LABEL uli
  MENU LABEL Ultimate Linux Installer
  KERNEL /live/vmlinuz
  APPEND initrd=/live/initrd.img boot=live components quiet splash hostname=uli-live username=uli
EOF

cat >"$IMG/boot/grub/grub.cfg" <<'EOF'
set timeout=3
set default=0
insmod all_video
insmod linux
insmod linuxefi
serial --unit=0 --speed=115200
terminal_input serial console
terminal_output serial console
menuentry "Ultimate Linux Installer" {
    echo "Booting Ultimate Linux Installer..."
    linux /live/vmlinuz boot=live components quiet splash hostname=uli-live username=uli console=tty0 console=ttyS0,115200n8
    initrd /live/initrd.img
}
EOF

echo "[2/3] UEFI ESP image..."
GRUB_EFI_DIR="$(uli_find_grub_efi_dir "$CHROOT")" || {
  echo "ERROR: GRUB EFI modules not found (chroot or host)" >&2
  exit 1
}
BOOT_IMG="$WORK/scratch/efi.img"
uli_make_efi_boot_image "$BOOT_IMG" "$IMG" "$LABEL" "$GRUB_EFI_DIR"
cp "$BOOT_IMG" "$IMG/EFI/BOOT/efiboot.img"

echo "[3/3] hybrid ISO (free space first)..."
mkdir -p "$OUT_DIR"
# Drop previous ISO so we have room on small LVs
rm -f "$OUT_DIR"/ultimate-linux-installer-*-amd64.iso \
  "$OUT_DIR"/ultimate-linux-installer.iso
uli_xorriso_hybrid "$OUT_ISO" "$LABEL" "$IMG"
ln -sfn "$(basename "$OUT_ISO")" "$OUT_DIR/ultimate-linux-installer.iso"
ls -lh "$OUT_ISO"
echo "ISO_READY=$OUT_ISO"
