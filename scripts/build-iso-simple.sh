#!/usr/bin/env bash
# Simple Ubuntu-based live ISO builder (avoids broken Ubuntu live-build 3.0 themes/grub-legacy)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${ULI_ISO_WORK:-/var/tmp/uli-iso}"
ARCH=amd64
DIST=jammy
MIRROR="${ULI_MIRROR:-http://archive.ubuntu.com/ubuntu}"
OUT_DIR="$ROOT/artifacts"
VERSION="${ULI_VERSION:-0.1.1}"
OUT_ISO="$OUT_DIR/ultimate-linux-installer-${VERSION}-amd64.iso"
LABEL="ULI_${VERSION//./_}"

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
  linux-image-generic live-boot live-config live-config-systemd live-tools \
  systemd-sysv sudo locales \
  network-manager ca-certificates \
  xorg openbox lightdm lightdm-gtk-greeter dbus-x11 xterm curl \
  open-vm-tools open-vm-tools-desktop \
  xserver-xorg-core xserver-xorg-input-libinput \
  xserver-xorg-video-vesa xserver-xorg-video-fbdev xserver-xorg-video-vmware \
  python3 python3-pip python3-venv python3-yaml python3-requests python3-psutil \
  libgl1 libglib2.0-0 libxkbcommon0 libxkbcommon-x11-0 libegl1 \
  libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-xinerama0 \
  libxcb-xkb1 libxcb-util1 \
  gdisk parted dosfstools e2fsprogs btrfs-progs xfsprogs lvm2 cryptsetup \
  efibootmgr grub-efi-amd64-bin grub-pc-bin shim-signed \
  squashfs-tools rsync curl wget gnupg fonts-dejavu-core \
  isolinux syslinux-common policykit-1

echo uli-live >"$CHROOT/etc/hostname"

chroot "$CHROOT" update-initramfs -u || true

echo "[3/6] install Ultimate Linux Installer app..."
mkdir -p "$CHROOT/opt/uli/src"
rsync -a \
  --exclude '.git' --exclude '.venv' --exclude 'live-build' \
  --exclude 'artifacts' --exclude 'docs/reference' --exclude '__pycache__' \
  "$ROOT/" "$CHROOT/opt/uli/src/"

chroot "$CHROOT" python3 -m pip install --no-cache-dir \
  /opt/uli/src fastapi 'uvicorn[standard]' PyYAML requests jsonschema psutil || \
chroot "$CHROOT" python3 -m pip install --break-system-packages --no-cache-dir \
  /opt/uli/src fastapi 'uvicorn[standard]' PyYAML requests jsonschema psutil
# PySide6 optional (legacy --ui qt)
chroot "$CHROOT" python3 -m pip install --no-cache-dir PySide6 2>/dev/null || true

cat >"$CHROOT/usr/local/bin/uli-start" <<'EOF'
#!/bin/sh
export PYTHONPATH=/usr/local/lib/python3.10/dist-packages
export ULI_SIMULATE_DISK=0
export ULI_DRY_RUN=0
mkdir -p /var/log/uli
exec >>/var/log/uli/uli-start.log 2>&1
echo "==== $(date -Is) DISPLAY=$DISPLAY ===="

# Web backend
uli --ui web --host 127.0.0.1 --port 8787 &
WEB_PID=$!
i=0
while [ "$i" -lt 60 ]; do
  if curl -sf http://127.0.0.1:8787/api/health >/dev/null 2>&1; then
    break
  fi
  i=$((i + 1))
  sleep 0.5
done

# Prefer Firefox kiosk (deb package); fall back to Chromium if present
if command -v firefox >/dev/null 2>&1; then
  exec firefox --kiosk --new-instance "http://127.0.0.1:8787/"
elif command -v chromium-browser >/dev/null 2>&1; then
  exec chromium-browser --kiosk --no-first-run --disable-infobars \
    --check-for-update-interval=31536000 "http://127.0.0.1:8787/"
elif command -v chromium >/dev/null 2>&1; then
  exec chromium --kiosk --no-first-run --disable-infobars "http://127.0.0.1:8787/"
fi

echo "No browser found — leaving web UI on :8787 (pid $WEB_PID)"
wait "$WEB_PID"
EOF
chmod +x "$CHROOT/usr/local/bin/uli-start"
if [ ! -x "$CHROOT/usr/local/bin/uli" ]; then
  printf '%s\n' '#!/bin/sh' \
    'export PYTHONPATH=/usr/local/lib/python3.10/dist-packages${PYTHONPATH:+:$PYTHONPATH}' \
    'exec python3 -m uli.main "$@"' >"$CHROOT/usr/local/bin/uli"
  chmod +x "$CHROOT/usr/local/bin/uli"
fi

mkdir -p "$CHROOT/etc/xdg/autostart" "$CHROOT/etc/xdg/openbox" "$CHROOT/etc/lightdm" \
  "$CHROOT/home/uli/.config/openbox" "$CHROOT/var/log/uli"
rm -f "$CHROOT/etc/xdg/autostart/uli.desktop" "$CHROOT/home/uli/.config/openbox/autostart"
# Hide Openbox desktop clutter; only launch the web UI
cat >"$CHROOT/etc/xdg/openbox/autostart" <<'EOF'
#!/bin/sh
xset -dpms
xset s off
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

chroot "$CHROOT" groupadd -f autologin
chroot "$CHROOT" groupadd -f nopasswdlogin
chroot "$CHROOT" useradd -m -G sudo,audio,video,netdev,autologin,nopasswdlogin -s /bin/bash uli || \
  chroot "$CHROOT" usermod -aG sudo,audio,video,netdev,autologin,nopasswdlogin uli || true
echo 'uli:uli' | chroot "$CHROOT" chpasswd
chroot "$CHROOT" chown -R uli:uli /home/uli /var/log/uli
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
TIMEOUT 1
DEFAULT uli
LABEL uli
  MENU LABEL Ultimate Linux Installer
  KERNEL /live/vmlinuz
  APPEND initrd=/live/initrd.img boot=live components quiet splash hostname=uli-live username=uli
EOF

# UEFI GRUB (must succeed — never ship BIOS-only)
# shellcheck source=lib-iso-uefi.sh
source "$ROOT/scripts/lib-iso-uefi.sh"

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

GRUB_EFI_DIR="$(uli_find_grub_efi_dir "$CHROOT")" || {
  echo "ERROR: install grub-efi-amd64-bin in chroot/host before building" >&2
  exit 1
}
BOOT_IMG="$WORK/scratch/efi.img"
uli_make_efi_boot_image "$BOOT_IMG" "$IMG" "$LABEL" "$GRUB_EFI_DIR"
cp "$BOOT_IMG" "$IMG/EFI/BOOT/efiboot.img"

echo "[6/6] create hybrid ISO..."
mkdir -p "$OUT_DIR"
uli_xorriso_hybrid "$OUT_ISO" "$LABEL" "$IMG"

ln -sfn "$(basename "$OUT_ISO")" "$OUT_DIR/ultimate-linux-installer.iso"
ls -lh "$OUT_ISO"
echo "ISO: $OUT_ISO"
