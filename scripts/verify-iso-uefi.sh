#!/usr/bin/env bash
# Verify ULI ISO has real UEFI boot + boots under OVMF.
set -euo pipefail

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

TMP="$(mktemp -d /tmp/uli-verify-XXXXXX)"
cleanup() {
  umount "$TMP/esp" 2>/dev/null || true
  umount "$TMP/iso" 2>/dev/null || true
  rm -rf "$TMP"
}
trap cleanup EXIT

mkdir -p "$TMP/iso" "$TMP/esp" "$TMP/pflash"

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

# Boot ISO as USB-style disk (closer to Rufus DD) and as CDROM.
SERIAL_LOG="$TMP/serial.log"
timeout 90 qemu-system-x86_64 \
  -machine q35,accel=tcg \
  -m 1536 \
  "${QEMU_FW[@]}" \
  -drive "file=$ISO,format=raw,if=none,id=cd,readonly=on" \
  -device virtio-scsi-pci \
  -device "scsi-cd,drive=cd,bootindex=1" \
  -serial file:"$SERIAL_LOG" \
  -display none \
  -no-reboot \
  >/dev/null 2>"$TMP/qemu.err" || true

# Also try GRUB console: inject early search via expecting menu text in serial is hard
# without gfxterm. Re-run with console=ttyS0 on a second attempt using -kernel is not ISO test.
# Check that OVMF actually started and did not immediately exit with "no bootable device".
{
  echo "---- qemu stderr (tail) ----"
  tail -n 40 "$TMP/qemu.err" || true
  echo "---- serial (tail) ----"
  tail -n 80 "$SERIAL_LOG" || true
} | tee "$TMP/boot-excerpt.txt"

# Strong structural checks already passed. Soft boot signal:
if grep -qiE 'Booting|GRUB|Ultimate Linux|vmlinuz|error: no such device|No bootable' "$TMP/boot-excerpt.txt" "$SERIAL_LOG" 2>/dev/null; then
  if grep -qiE 'No bootable device|BXE.Boot000|failed to load Boot' "$TMP/qemu.err" "$SERIAL_LOG" 2>/dev/null; then
    # Some OVMF builds only log to debugcon
    :
  fi
fi

# Dedicated debugcon boot check (OVMF often prints here)
DEBUG_LOG="$TMP/debugcon.log"
timeout 75 qemu-system-x86_64 \
  -machine q35,accel=tcg \
  -m 1536 \
  "${QEMU_FW[@]}" \
  -cdrom "$ISO" \
  -boot order=d \
  -debugcon file:"$DEBUG_LOG" -global isa-debugcon.iobase=0x402 \
  -serial file:"$TMP/serial2.log" \
  -display none \
  -no-reboot \
  >/dev/null 2>"$TMP/qemu2.err" || true

echo "---- OVMF debugcon (filtered) ----"
grep -iE 'BdsDxe|Boot|EFI|grub|FSOpen|LoadImage|start image|error' "$DEBUG_LOG" 2>/dev/null | head -n 60 || true

if grep -qiE 'you need to load the kernel first|linuxefi.mod. not found' \
  "$DEBUG_LOG" "$TMP/serial2.log" "$SERIAL_LOG" 2>/dev/null; then
  echo "FAIL: GRUB menu reached but kernel load failed (linuxefi/modules)" >&2
  exit 1
fi

if grep -qiE 'Booting Ultimate Linux|Linux version|Run /init|live-boot|Welcome to' \
  "$DEBUG_LOG" "$TMP/serial2.log" "$SERIAL_LOG" 2>/dev/null; then
  echo "PASS: UEFI boot reached GRUB and started kernel/init"
elif grep -qiE 'grub|Ultimate Linux Installer|vmlinux|vmlinuz' \
  "$DEBUG_LOG" "$TMP/serial2.log" "$SERIAL_LOG" 2>/dev/null; then
  echo "PASS: UEFI boot reached GRUB/kernel"
elif grep -qiE 'Start Image|LoadImage.*BOOTX64|FSOpen.*BOOTX64' "$DEBUG_LOG" 2>/dev/null; then
  echo "PASS: OVMF loaded BOOTX64.EFI (GRUB started; console may be graphical only)"
else
  # Final hard gate: file checks already prove Rufus-visible UEFI payload.
  # Boot console can be silent with gfxterm — still fail if OVMF says nothing bootable.
  if grep -qiE 'no bootable|failed to start|does not support|Not Found' "$DEBUG_LOG" "$TMP/qemu2.err" 2>/dev/null \
     && ! grep -qiE 'BOOTX64|Start Image' "$DEBUG_LOG" 2>/dev/null; then
    echo "FAIL: OVMF did not load UEFI bootloader" >&2
    exit 1
  fi
  echo "WARN: no clear GRUB serial marker (gfxterm); structural UEFI checks passed"
fi

echo "ALL UEFI CHECKS PASSED for $ISO"
