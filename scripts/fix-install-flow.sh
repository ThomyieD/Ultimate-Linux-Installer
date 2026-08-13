#!/bin/bash
set -euo pipefail
ROOT=/root/Linux-Installer/github/Ultimate-Linux-Installer
CH=/var/tmp/uli-iso/chroot
WORK=/var/tmp/uli-iso
IMG=$WORK/image
VERSION=0.2.8
OUT_ISO=$ROOT/artifacts/ultimate-linux-installer-${VERSION}-amd64.iso
LABEL=ULI_0_2_8
PYSITE=$CH/usr/local/lib/python3.10/dist-packages

source "$ROOT/scripts/lib-iso-uefi.sh"

echo "[1] sync app + adapters..."
rm -rf "$PYSITE/uli" "$PYSITE/adapters"
cp -a "$ROOT/app/uli" "$PYSITE/uli"
cp -a "$ROOT/adapters" "$PYSITE/adapters"

echo "[2] partition tools..."
mount --bind /dev "$CH/dev" 2>/dev/null || true
mount --bind /dev/pts "$CH/dev/pts" 2>/dev/null || true
mount -t proc proc "$CH/proc" 2>/dev/null || true
mount -t sysfs sys "$CH/sys" 2>/dev/null || true
cp /etc/resolv.conf "$CH/etc/resolv.conf" 2>/dev/null || true
chroot "$CH" apt-get update -qq
chroot "$CH" apt-get install -y --no-install-recommends \
  gdisk parted dosfstools e2fsprogs util-linux
chroot "$CH" apt-get clean
rm -rf "$CH/var/lib/apt/lists"/* "$CH/tmp"/* "$CH/var/tmp"/*

for m in "$CH/dev/pts" "$CH/dev" "$CH/proc" "$CH/sys" "$CH/run"; do
  while mountpoint -q "$m" 2>/dev/null; do umount -l "$m" || break; sleep 0.2; done
done
mkdir -p "$CH/proc" "$CH/sys" "$CH/dev" "$CH/run/lock" "$CH/tmp" "$CH/boot" "$CH/var/cache/uli"
chmod 1777 "$CH/tmp"

mount -t proc proc "$CH/proc" 2>/dev/null || true
mount --bind /dev "$CH/dev" 2>/dev/null || true
chroot "$CH" env PYTHONPATH=/usr/local/lib/python3.10/dist-packages python3 - <<'PY'
from uli.web.server import create_app
from uli.install.job import get_job
app = create_app(simulate_disk=True)
paths = {getattr(r, "path", None) for r in app.routes}
assert "/api/install/start" in paths
assert "/api/install/status" in paths
print("install_api_ok", get_job()["status"])
PY
umount -l "$CH/proc" 2>/dev/null || true
umount -l "$CH/dev" 2>/dev/null || true

echo "[3] squash + ISO..."
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
