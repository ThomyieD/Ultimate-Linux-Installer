#!/bin/bash
# Fix cache permissions + install flow 0.2.9
set -euo pipefail
ROOT=/root/Linux-Installer/github/Ultimate-Linux-Installer
CH=/var/tmp/uli-iso/chroot
WORK=/var/tmp/uli-iso
IMG=$WORK/image
VERSION=0.2.9
OUT_ISO=$ROOT/artifacts/ultimate-linux-installer-${VERSION}-amd64.iso
LABEL=ULI_0_2_9
PYSITE=$CH/usr/local/lib/python3.10/dist-packages

source "$ROOT/scripts/lib-iso-uefi.sh"

echo "[1] sync app..."
rm -rf "$PYSITE/uli" "$PYSITE/adapters"
cp -a "$ROOT/app/uli" "$PYSITE/uli"
cp -a "$ROOT/adapters" "$PYSITE/adapters"

# Writable cache for live user
mkdir -p "$CH/var/cache/uli" "$CH/home/uli/.cache/uli" "$CH/tmp/uli-cache"
chown -R 1000:1000 "$CH/var/cache/uli" "$CH/home/uli/.cache" 2>/dev/null || true
# live-build often uses uid 1000 for first user; also try uli by name in chroot later
chmod 1777 "$CH/var/cache/uli" "$CH/tmp/uli-cache"

for m in "$CH/dev/pts" "$CH/dev" "$CH/proc" "$CH/sys" "$CH/run"; do
  while mountpoint -q "$m" 2>/dev/null; do umount -l "$m" || break; sleep 0.2; done
done
mkdir -p "$CH/proc" "$CH/sys" "$CH/dev" "$CH/run/lock" "$CH/tmp" "$CH/boot"
chmod 1777 "$CH/tmp"

# Ensure uli-start prepares cache at runtime
if [ -f "$CH/usr/local/bin/uli-start" ]; then
  if ! grep -q 'var/cache/uli' "$CH/usr/local/bin/uli-start"; then
    sed -i '/mkdir -p \/var\/log\/uli/a\
mkdir -p /var/cache/uli /home/uli/.cache/uli /tmp/uli-cache\
chmod 1777 /var/cache/uli /tmp/uli-cache 2>/dev/null || true\
chown -R uli:uli /var/cache/uli /home/uli/.cache 2>/dev/null || true
' "$CH/usr/local/bin/uli-start"
  fi
fi

# Prefer rewriting the mkdir block via python for reliability
python3 - <<'PY'
from pathlib import Path
p = Path("/var/tmp/uli-iso/chroot/usr/local/bin/uli-start")
text = p.read_text(encoding="utf-8")
needle = "mkdir -p /var/log/uli /home/uli/.mozilla"
extra = """mkdir -p /var/log/uli /home/uli/.mozilla /var/cache/uli /home/uli/.cache/uli /tmp/uli-cache
chmod 1777 /var/cache/uli /tmp/uli-cache 2>/dev/null || true
chown -R uli:uli /var/cache/uli /home/uli/.cache 2>/dev/null || true"""
if "chmod 1777 /var/cache/uli" not in text:
    if needle in text:
        text = text.replace(needle, extra, 1)
    p.write_text(text, encoding="utf-8")
    print("uli-start patched")
else:
    print("uli-start already ok")
PY

mount -t proc proc "$CH/proc" 2>/dev/null || true
mount --bind /dev "$CH/dev" 2>/dev/null || true
chroot "$CH" bash -lc 'id uli; chown -R uli:uli /var/cache/uli /home/uli/.cache 2>/dev/null || chown -R 1000:1000 /var/cache/uli /home/uli/.cache; chmod 1777 /var/cache/uli'
chroot "$CH" env PYTHONPATH=/usr/local/lib/python3.10/dist-packages python3 - <<'PY'
from uli.install.job import _writable_cache_root
root = _writable_cache_root()
print("cache_root", root)
PY
umount -l "$CH/proc" 2>/dev/null || true
umount -l "$CH/dev" 2>/dev/null || true

echo "[2] squash + ISO..."
rm -f "$IMG/live/filesystem.squashfs"
rm -f "$ROOT/artifacts"/ultimate-linux-installer-*.iso
rm -f "$ROOT/artifacts"/ultimate-linux-installer.iso
mksquashfs "$CH" "$IMG/live/filesystem.squashfs" -comp xz -e boot
GRUB_EFI_DIR="$(uli_find_grub_efi_dir "$CH")"
BOOT_IMG=$WORK/scratch/efi.img
mkdir -p "$WORK/scratch" "$IMG/EFI/BOOT"
uli_make_efi_boot_image "$BOOT_IMG" "$IMG" "$LABEL" "$GRUB_EFI_DIR"
cp "$BOOT_IMG" "$IMG/EFI/BOOT/efiboot.img"
uli_xorriso_hybrid "$OUT_ISO" "$LABEL" "$IMG"
ln -sfn "$(basename "$OUT_ISO")" "$ROOT/artifacts/ultimate-linux-installer.iso"
ls -lh "$OUT_ISO"
echo "ISO_READY=$OUT_ISO"
