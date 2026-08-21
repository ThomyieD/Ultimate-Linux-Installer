#!/usr/bin/env bash
# Verify ULI ISO has real UEFI boot + boots under OVMF.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
# shellcheck source=scripts/lib-debian-archive-keyring.sh
source "$ROOT/scripts/lib-debian-archive-keyring.sh"

ISO="${1:-}"
if [ -z "$ISO" ]; then
  echo "usage: $0 /path/to.iso" >&2
  exit 2
fi
[ -f "$ISO" ] || { echo "ERROR: ISO not found: $ISO" >&2; exit 1; }

need() { command -v "$1" >/dev/null || { echo "missing: $1" >&2; exit 1; }; }
need xorriso
need mount
need umount
need file
need qemu-system-x86_64
need gpg
need sha256sum

TMP="$(mktemp -d /tmp/uli-verify-XXXXXX)"
cleanup() {
  umount "$TMP/rootfs" 2>/dev/null || true
  umount "$TMP/esp" 2>/dev/null || true
  umount "$TMP/iso" 2>/dev/null || true
  rm -rf "$TMP"
}
trap cleanup EXIT

mkdir -p "$TMP/iso" "$TMP/esp" "$TMP/pflash" "$TMP/rootfs"

echo "== El Torito =="
xorriso -indev "$ISO" -report_el_torito plain 2>&1 | tee "$TMP/eltorito.txt"
grep -q 'UEFI' "$TMP/eltorito.txt" || { echo "FAIL: no UEFI El Torito entry" >&2; exit 1; }
grep -q 'BIOS' "$TMP/eltorito.txt" || { echo "FAIL: no BIOS El Torito entry" >&2; exit 1; }

echo "== System area (hybrid) =="
xorriso -indev "$ISO" -report_system_area plain 2>&1 | tee "$TMP/sysarea.txt"
# isohybrid should leave a non-empty system area / MBR
if grep -qi 'No System Area was loaded' "$TMP/sysarea.txt"; then
  echo "FAIL: no hybrid system area (isohybrid-mbr missing?)" >&2
  exit 1
fi

echo "== Mount ISO + ESP =="
mount -o loop,ro "$ISO" "$TMP/iso"
[ -s "$TMP/iso/EFI/BOOT/BOOTX64.EFI" ] || {
  echo "FAIL: ISO lacks EFI/BOOT/BOOTX64.EFI" >&2
  exit 1
}
[ -s "$TMP/iso/EFI/BOOT/efiboot.img" ] || {
  echo "FAIL: ISO lacks EFI/BOOT/efiboot.img" >&2
  exit 1
}
ISO_EFI_SIZE="$(stat -c%s "$TMP/iso/EFI/BOOT/BOOTX64.EFI")"
echo "ISO BOOTX64.EFI: $ISO_EFI_SIZE bytes — $(file -b "$TMP/iso/EFI/BOOT/BOOTX64.EFI")"
[ "$ISO_EFI_SIZE" -ge 100000 ] || {
  echo "FAIL: BOOTX64.EFI too small ($ISO_EFI_SIZE)" >&2
  exit 1
}
file "$TMP/iso/EFI/BOOT/BOOTX64.EFI" | grep -qi 'EFI' || {
  echo "FAIL: BOOTX64.EFI is not an EFI binary" >&2
  exit 1
}

mount -o loop,ro "$TMP/iso/EFI/BOOT/efiboot.img" "$TMP/esp"
ESP_EFI="$TMP/esp/EFI/BOOT/BOOTX64.EFI"
[ -s "$ESP_EFI" ] || { echo "FAIL: ESP BOOTX64.EFI empty/missing" >&2; exit 1; }
ESP_SIZE="$(stat -c%s "$ESP_EFI")"
echo "ESP BOOTX64.EFI: $ESP_SIZE bytes — $(file -b "$ESP_EFI")"
[ "$ESP_SIZE" -ge 100000 ] || {
  echo "FAIL: ESP BOOTX64.EFI too small ($ESP_SIZE)" >&2
  exit 1
}
[ -f "$TMP/esp/EFI/BOOT/grub.cfg" ] || {
  echo "FAIL: ESP missing EFI/BOOT/grub.cfg" >&2
  exit 1
}
[ -f "$TMP/iso/boot/grub/grub.cfg" ] || {
  echo "FAIL: ISO missing boot/grub/grub.cfg" >&2
  exit 1
}

echo "== Debian 13 archive keyring trust anchors =="
[ -s "$TMP/iso/live/filesystem.squashfs" ] || {
  echo "FAIL: ISO lacks live/filesystem.squashfs" >&2
  exit 1
}
mount -o loop,ro "$TMP/iso/live/filesystem.squashfs" "$TMP/rootfs"
uli_debian_archive_keyring_verify_installed "$TMP/rootfs"
umount "$TMP/rootfs" || umount -l "$TMP/rootfs" || true

umount "$TMP/esp" || umount -l "$TMP/esp" || true
umount "$TMP/iso" || umount -l "$TMP/iso" || true

echo "== QEMU OVMF UEFI boot smoke test =="
OVMF_CODE=""
OVMF_VARS_SRC=""
for c in \
  /usr/share/OVMF/OVMF_CODE_4M.fd \
  /usr/share/OVMF/OVMF_CODE.fd \
  /usr/share/ovmf/OVMF.fd; do
  [ -f "$c" ] && OVMF_CODE="$c" && break
done
for v in \
  /usr/share/OVMF/OVMF_VARS_4M.fd \
  /usr/share/OVMF/OVMF_VARS.fd; do
  [ -f "$v" ] && OVMF_VARS_SRC="$v" && break
done
[ -n "$OVMF_CODE" ] || { echo "FAIL: OVMF firmware not installed" >&2; exit 1; }

VARS_COPY="$TMP/pflash/vars.fd"
if [ -n "$OVMF_VARS_SRC" ]; then
  cp "$OVMF_VARS_SRC" "$VARS_COPY"
  QEMU_FW=(
    -drive "if=pflash,format=raw,readonly=on,file=$OVMF_CODE"
    -drive "if=pflash,format=raw,file=$VARS_COPY"
  )
else
  QEMU_FW=(-bios "$OVMF_CODE")
fi

# Boot the ISO under OVMF.  v0.3 emits a marker only after systemd has started
# the real ULI backend and its health endpoint answers inside the live system.
SERIAL_LOG="$TMP/serial.log"
set +e
timeout 180 qemu-system-x86_64 \
  -machine q35,accel=tcg \
  -m 2048 \
  "${QEMU_FW[@]}" \
  -cdrom "$ISO" \
  -boot order=d \
  -netdev user,id=net0 \
  -device virtio-net-pci,netdev=net0 \
  -serial file:"$SERIAL_LOG" \
  -display none \
  -no-reboot \
  >/dev/null 2>"$TMP/qemu.err"
QEMU_STATUS=$?
set -e

{
  echo "---- qemu stderr (tail) ----"
  tail -n 40 "$TMP/qemu.err" || true
  echo "---- serial (tail) ----"
  tail -n 80 "$SERIAL_LOG" || true
} | tee "$TMP/boot-excerpt.txt"

if grep -qiE 'you need to load the kernel first|linuxefi\.mod.*not found|no bootable device' \
  "$SERIAL_LOG" "$TMP/qemu.err" 2>/dev/null; then
  echo "FAIL: GRUB menu reached but kernel load failed (linuxefi/modules)" >&2
  exit 1
fi

if ! grep -q 'ULI_LIVE_READY' "$SERIAL_LOG"; then
  echo "FAIL: live system did not start a healthy ULI backend (qemu status $QEMU_STATUS)" >&2
  exit 1
fi

echo "PASS: OVMF booted the live system and the ULI backend became healthy"
echo "ALL UEFI CHECKS PASSED for $ISO"
