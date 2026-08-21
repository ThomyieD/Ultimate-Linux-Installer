#!/usr/bin/env bash
# Shared UEFI boot image helpers for ULI ISO builds.
# Requires: grub-mkimage, mkfs.vfat, mount, umount

uli_find_grub_efi_dir() {
  local chroot="${1:-}"
  local d
  for d in \
    "${chroot:+$chroot/usr/lib/grub/x86_64-efi}" \
    /usr/lib/grub/x86_64-efi \
    /usr/lib/grub/x86_64-efi-signed; do
    if [ -n "$d" ] && [ -f "$d/moddep.lst" ]; then
      printf '%s\n' "$d"
      return 0
    fi
  done
  return 1
}

# Build a FAT ESP image with a real GRUB BOOTX64.EFI (not shim-only, not empty).
# Args: boot_img_path image_dir label grub_efi_modules_dir
uli_make_efi_boot_image() {
  local boot_img="$1"
  local img_dir="$2"
  local label="$3"
  local grub_dir="$4"
  local mnt size_mb=16
  local efi_out cfg_esp

  [ -f "$grub_dir/moddep.lst" ] || {
    echo "ERROR: GRUB EFI modules missing at $grub_dir (moddep.lst)" >&2
    return 1
  }
  command -v grub-mkimage >/dev/null || {
    echo "ERROR: grub-mkimage not found" >&2
    return 1
  }

  mkdir -p "$img_dir/EFI/BOOT" "$img_dir/boot/grub"
  mnt="$(mktemp -d /tmp/uli-efi-XXXXXX)"

  rm -f "$boot_img"
  dd if=/dev/zero of="$boot_img" bs=1M count="$size_mb" status=none
  mkfs.vfat -n "ULI_ESP" "$boot_img" >/dev/null

  mount "$boot_img" "$mnt"
  mkdir -p "$mnt/EFI/BOOT" "$mnt/boot/grub"

  efi_out="$mnt/EFI/BOOT/BOOTX64.EFI"
  # Prefix points at ESP path so early cfg is found without ISO search.
  grub-mkimage \
    -d "$grub_dir" \
    -O x86_64-efi \
    -o "$efi_out" \
    -p /EFI/BOOT \
    all_video boot cat chain configfile echo fat ext2 \
    gfxmenu gfxterm gzio halt iso9660 linux loadenv loopback \
    ls lsefi lsefimmap normal part_gpt part_msdos probe reboot \
    regexp search search_fs_file search_fs_uuid search_label \
    serial sleep terminal test true video

  if [ ! -s "$efi_out" ]; then
    umount "$mnt" || true
    rmdir "$mnt" || true
    echo "ERROR: BOOTX64.EFI missing or empty after grub-mkimage" >&2
    return 1
  fi

  # Minimal ESP cfg: find ISO by volume label, then load full menu.
  cfg_esp="$mnt/EFI/BOOT/grub.cfg"
  cat >"$cfg_esp" <<EOF
search --no-floppy --set=root --label ${label}
set prefix=(\$root)/boot/grub
configfile \$prefix/grub.cfg
EOF

  cp "$img_dir/boot/grub/grub.cfg" "$mnt/boot/grub/grub.cfg"

  # Keep the complete module tree on the ISO for runtime dependencies and
  # firmware variants. Noble's x86_64-efi build uses linux.mod directly and
  # deliberately does not ship the downstream-only linuxefi.mod.
  mkdir -p "$img_dir/boot/grub/x86_64-efi"
  cp -a "$grub_dir"/. "$img_dir/boot/grub/x86_64-efi/"

  # Also expose EFI files on the ISO9660 tree (Rufus ISO-mode / some firmware).
  cp -f "$efi_out" "$img_dir/EFI/BOOT/BOOTX64.EFI"
  cp -f "$cfg_esp" "$img_dir/EFI/BOOT/grub.cfg"

  umount "$mnt"
  rmdir "$mnt"

  local bytes
  bytes="$(stat -c%s "$img_dir/EFI/BOOT/BOOTX64.EFI")"
  if [ "$bytes" -lt 100000 ]; then
    echo "ERROR: BOOTX64.EFI too small (${bytes} bytes) — UEFI boot would fail" >&2
    return 1
  fi
  echo "UEFI BOOTX64.EFI OK (${bytes} bytes) via modules in $grub_dir"
}

uli_xorriso_hybrid() {
  local out_iso="$1"
  local label="$2"
  local img_dir="$3"
  local mbr="${4:-}"

  if [ -z "$mbr" ]; then
    for mbr in /usr/lib/ISOLINUX/isohdpfx.bin /usr/lib/syslinux/isohdpfx.bin; do
      [ -f "$mbr" ] && break
    done
  fi
  [ -f "$mbr" ] || {
    echo "ERROR: isohdpfx.bin not found (install isolinux)" >&2
    return 1
  }
  [ -s "$img_dir/EFI/BOOT/efiboot.img" ] || {
    echo "ERROR: efiboot.img missing" >&2
    return 1
  }
  [ -s "$img_dir/EFI/BOOT/BOOTX64.EFI" ] || {
    echo "ERROR: ISO EFI/BOOT/BOOTX64.EFI missing — refusing to ship BIOS-only ISO" >&2
    return 1
  }
  [ -f "$img_dir/isolinux/isolinux.bin" ] || {
    echo "ERROR: isolinux.bin missing" >&2
    return 1
  }

  # Hybrid MBR (BIOS) + GPT protective EFI partition from El Torito EFI image.
  xorriso -as mkisofs \
    -iso-level 3 \
    -full-iso9660-filenames \
    -volid "$label" \
    -eltorito-boot isolinux/isolinux.bin \
    -eltorito-catalog isolinux/boot.cat \
    -no-emul-boot -boot-load-size 4 -boot-info-table \
    -isohybrid-mbr "$mbr" \
    -eltorito-alt-boot \
    -e EFI/BOOT/efiboot.img \
    -no-emul-boot \
    -isohybrid-gpt-basdat \
    -output "$out_iso" \
    "$img_dir"
}
