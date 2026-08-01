#!/usr/bin/env bash
# Simple Ubuntu-based live ISO builder (avoids broken Ubuntu live-build 3.0 themes/grub-legacy)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${ULI_ISO_WORK:-/var/tmp/uli-iso}"
ARCH=amd64
DIST=jammy
MIRROR="${ULI_MIRROR:-http://archive.ubuntu.com/ubuntu}"
OUT_DIR="$ROOT/artifacts"
OUT_ISO="$OUT_DIR/ultimate-linux-installer-0.1.0-amd64.iso"
LABEL="ULI_0_1_0"

export DEBIAN_FRONTEND=noninteractive

need() { command -v "$1" >/dev/null || { echo "missing: $1" >&2; exit 1; }; }
need debootstrap
need mksquashfs
need xorriso
need rsync
need mkfs.vfat

rm -rf "$WORK"
mkdir -p "$WORK"/{chroot,image/{live,boot/grub,EFI/BOOT},scratch}
CHROOT="$WORK/chroot"
IMG="$WORK/image"

echo "[1/6] debootstrap $DIST..."
debootstrap --arch="$ARCH" --variant=minbase "$DIST" "$CHROOT" "$MIRROR"

echo "[2/6] configure apt + install packages..."
cat >"$CHROOT/etc/apt/sources.list" <<EOF
deb $MIRROR $DIST main restricted universe multiverse
deb $MIRROR $DIST-updates main restricted universe multiverse
EOF

cp /etc/resolv.conf "$CHROOT/etc/resolv.conf"
mount --bind /dev "$CHROOT/dev"
mount --bind /dev/pts "$CHROOT/dev/pts"
mount -t proc proc "$CHROOT/proc"
mount -t sysfs sysfs "$CHROOT/sys"

cleanup() {
  umount -lf "$CHROOT/dev/pts" 2>/dev/null || true
  umount -lf "$CHROOT/dev" 2>/dev/null || true
  umount -lf "$CHROOT/proc" 2>/dev/null || true
  umount -lf "$CHROOT/sys" 2>/dev/null || true
}
trap cleanup EXIT

chroot "$CHROOT" apt-get update
chroot "$CHROOT" apt-get install -y --no-install-recommends \
  linux-image-generic live-boot \
  systemd-sysv sudo locales \
  network-manager ca-certificates \
  xorg openbox lightdm lightdm-gtk-greeter dbus-x11 xterm \
  python3 python3-pip python3-venv python3-yaml python3-requests python3-psutil \
  libgl1 libglib2.0-0 libxkbcommon0 libxcb-cursor0 libegl1 \
  gdisk parted dosfstools e2fsprogs btrfs-progs xfsprogs lvm2 cryptsetup \
  efibootmgr grub-efi-amd64-bin grub-pc-bin shim-signed \
  squashfs-tools rsync curl wget gnupg fonts-dejavu-core \
  isolinux syslinux-common

chroot "$CHROOT" update-initramfs -u || true

echo "[3/6] install Ultimate Linux Installer app..."
mkdir -p "$CHROOT/opt/uli/src"
rsync -a \
  --exclude '.git' --exclude '.venv' --exclude 'live-build' \
  --exclude 'artifacts' --exclude 'docs/reference' --exclude '__pycache__' \
  "$ROOT/" "$CHROOT/opt/uli/src/"

chroot "$CHROOT" python3 -m pip install --no-cache-dir \
  /opt/uli/src PySide6 PyYAML requests jsonschema psutil || \
chroot "$CHROOT" python3 -m pip install --break-system-packages --no-cache-dir \
  /opt/uli/src PySide6 PyYAML requests jsonschema psutil

cat >"$CHROOT/usr/local/bin/uli-start" <<'EOF'
#!/bin/sh
export ULI_SIMULATE_DISK=0
export ULI_DRY_RUN=0
export QT_QPA_PLATFORM=xcb
sleep 1
exec uli --lang de || exec python3 -m uli.main --lang de
EOF
chmod +x "$CHROOT/usr/local/bin/uli-start"
if [ ! -x "$CHROOT/usr/local/bin/uli" ]; then
  printf '#!/bin/sh\nexec python3 -m uli.main "$@"\n' >"$CHROOT/usr/local/bin/uli"
  chmod +x "$CHROOT/usr/local/bin/uli"
fi

mkdir -p "$CHROOT/etc/xdg/autostart" "$CHROOT/etc/xdg/openbox" "$CHROOT/etc/lightdm"
cat >"$CHROOT/etc/xdg/autostart/uli.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Ultimate Linux Installer
Exec=/usr/local/bin/uli-start
X-GNOME-Autostart-enabled=true
EOF
cat >"$CHROOT/etc/xdg/openbox/autostart" <<'EOF'
#!/bin/sh
/usr/local/bin/uli-start &
EOF
chmod +x "$CHROOT/etc/xdg/openbox/autostart"
cat >"$CHROOT/etc/lightdm/lightdm.conf" <<'EOF'
[Seat:*]
autologin-user=uli
autologin-user-timeout=0
user-session=openbox
greeter-session=lightdm-gtk-greeter
EOF

chroot "$CHROOT" useradd -m -G sudo,audio,video,netdev -s /bin/bash uli || true
echo 'uli:uli' | chroot "$CHROOT" chpasswd
chroot "$CHROOT" systemctl enable NetworkManager.service || true
chroot "$CHROOT" systemctl enable lightdm.service || true

# Live boot defaults
mkdir -p "$CHROOT/etc/live/config.conf.d"
echo 'LIVE_USERNAME="uli"' >"$CHROOT/etc/live/config.conf.d/uli.conf"
echo 'LIVE_USER_DEFAULT_GROUPS="audio cdrom dip floppy video plugdev netdev sudo"' >>"$CHROOT/etc/live/config.conf.d/uli.conf"

echo "[4/6] squashfs..."
# cleanup apt caches before squash
chroot "$CHROOT" apt-get clean
rm -rf "$CHROOT/var/lib/apt/lists"/* "$CHROOT/tmp"/* "$CHROOT/var/tmp"/*
cleanup
trap - EXIT

mksquashfs "$CHROOT" "$IMG/live/filesystem.squashfs" -comp xz -e boot
cp "$CHROOT"/boot/vmlinuz-* "$IMG/live/vmlinuz"
cp "$CHROOT"/boot/initrd.img-* "$IMG/live/initrd.img" || \
  cp "$CHROOT"/boot/initrd.img-* "$IMG/live/initrd.img"

echo "[5/6] bootloader files..."
# BIOS isolinux
mkdir -p "$IMG/isolinux"
if [ -f /usr/lib/ISOLINUX/isolinux.bin ]; then
  cp /usr/lib/ISOLINUX/isolinux.bin "$IMG/isolinux/"
  cp /usr/lib/syslinux/modules/bios/*.c32 "$IMG/isolinux/" 2>/dev/null || true
elif [ -f "$CHROOT/usr/lib/ISOLINUX/isolinux.bin" ]; then
  cp "$CHROOT/usr/lib/ISOLINUX/isolinux.bin" "$IMG/isolinux/"
  cp "$CHROOT/usr/lib/syslinux/modules/bios/"*.c32 "$IMG/isolinux/" 2>/dev/null || true
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

# UEFI GRUB
cat >"$IMG/boot/grub/grub.cfg" <<'EOF'
set timeout=5
set default=0
menuentry "Ultimate Linux Installer" {
    linux /live/vmlinuz boot=live components quiet splash hostname=uli-live username=uli
    initrd /live/initrd.img
}
EOF

# Create EFI boot image
BOOT_IMG="$WORK/scratch/efi.img"
dd if=/dev/zero of="$BOOT_IMG" bs=1M count=10 status=none
mkfs.vfat "$BOOT_IMG" >/dev/null
mkdir -p "$WORK/scratch/efimount"
mount "$BOOT_IMG" "$WORK/scratch/efimount"
mkdir -p "$WORK/scratch/efimount/EFI/BOOT"
if [ -f "$CHROOT/usr/lib/shim/shimx64.efi.signed.latest" ]; then
  cp "$CHROOT/usr/lib/shim/shimx64.efi.signed.latest" "$WORK/scratch/efimount/EFI/BOOT/BOOTX64.EFI"
elif [ -f "$CHROOT/usr/lib/shim/shimx64.efi.signed" ]; then
  cp "$CHROOT/usr/lib/shim/shimx64.efi.signed" "$WORK/scratch/efimount/EFI/BOOT/BOOTX64.EFI"
elif [ -f /usr/lib/shim/shimx64.efi.signed ]; then
  cp /usr/lib/shim/shimx64.efi.signed "$WORK/scratch/efimount/EFI/BOOT/BOOTX64.EFI"
else
  # Fallback: grub efi only
  grub-mkimage -O x86_64-efi -o "$WORK/scratch/efimount/EFI/BOOT/BOOTX64.EFI" \
    -p /boot/grub iso9660 fat part_gpt part_msdos normal linux search search_fs_uuid search_label configfile echo ls || true
fi
cp "$IMG/boot/grub/grub.cfg" "$WORK/scratch/efimount/EFI/BOOT/grub.cfg" 2>/dev/null || true
umount "$WORK/scratch/efimount"
cp "$BOOT_IMG" "$IMG/EFI/BOOT/efiboot.img"
cp -r "$WORK/scratch/efimount/EFI/BOOT/." "$IMG/EFI/BOOT/" 2>/dev/null || true

echo "[6/6] create hybrid ISO..."
mkdir -p "$OUT_DIR"
xorriso -as mkisofs \
  -iso-level 3 \
  -full-iso9660-filenames \
  -volid "$LABEL" \
  -eltorito-boot isolinux/isolinux.bin \
  -eltorito-catalog isolinux/boot.cat \
  -no-emul-boot -boot-load-size 4 -boot-info-table \
  -eltorito-alt-boot \
  -e EFI/BOOT/efiboot.img \
  -no-emul-boot \
  -isohybrid-gpt-basdat \
  -output "$OUT_ISO" \
  "$IMG"

ln -sfn "$(basename "$OUT_ISO")" "$OUT_DIR/ultimate-linux-installer.iso"
ls -lh "$OUT_ISO"
echo "ISO: $OUT_ISO"
