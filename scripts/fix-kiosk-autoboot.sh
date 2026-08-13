#!/bin/bash
# Fix black screen (Firefox start) + skip GRUB menu, then rebuild ISO 0.2.1
set -euo pipefail
ROOT=/root/Linux-Installer/github/Ultimate-Linux-Installer
CH=/var/tmp/uli-iso/chroot
WORK=/var/tmp/uli-iso
IMG=$WORK/image
VERSION=0.2.1
OUT_ISO=$ROOT/artifacts/ultimate-linux-installer-${VERSION}-amd64.iso
LABEL=ULI_0_2_1

# shellcheck source=lib-iso-uefi.sh
source "$ROOT/scripts/lib-iso-uefi.sh"

echo "[deps] firefox runtime libraries..."
mount --bind /dev "$CH/dev" 2>/dev/null || true
mount --bind /dev/pts "$CH/dev/pts" 2>/dev/null || true
mount -t proc proc "$CH/proc" 2>/dev/null || true
mount -t sysfs sys "$CH/sys" 2>/dev/null || true
cp /etc/resolv.conf "$CH/etc/resolv.conf" 2>/dev/null || true
chroot "$CH" apt-get update -qq
chroot "$CH" apt-get install -y --no-install-recommends \
  libdbus-glib-1-2 libasound2 libgtk-3-0 libxt6 libx11-xcb1 \
  libxcb-shm0 libatomic1 libnss3 libnspr4 libxcomposite1 \
  libxdamage1 libxfixes3 libxrandr2 libxcursor1 libxi6 \
  libpangocairo-1.0-0 libatk1.0-0 libgdk-pixbuf-2.0-0 \
  fonts-liberation dbus-x11 curl
chroot "$CH" apt-get clean
rm -rf "$CH/var/lib/apt/lists"/* "$CH/tmp"/* "$CH/var/tmp"/*
umount -l "$CH/dev/pts" 2>/dev/null || true
umount -l "$CH/dev" 2>/dev/null || true
umount -l "$CH/proc" 2>/dev/null || true
umount -l "$CH/sys" 2>/dev/null || true

# Ensure Mozilla Firefox tarball is present
if [ ! -x "$CH/opt/firefox/firefox-bin" ]; then
  bash "$ROOT/scripts/install-firefox-tarball.sh" "$CH"
fi

echo "[start] rewrite uli-start (cd into /opt/firefox)..."
cat >"$CH/usr/local/bin/uli-start" <<'EOF'
#!/bin/sh
export PYTHONPATH=/usr/local/lib/python3.10/dist-packages
export ULI_SIMULATE_DISK=0
export ULI_DRY_RUN=0
export MOZ_DISABLE_CONTENT_SANDBOX=1
export MOZ_DBUS_REMOTE=1
mkdir -p /var/log/uli /home/uli/.mozilla
exec >>/var/log/uli/uli-start.log 2>&1
echo "==== $(date -Is) DISPLAY=$DISPLAY USER=$(id) ===="

# Session bus (needed by Firefox)
if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ] && command -v dbus-launch >/dev/null 2>&1; then
  eval "$(dbus-launch --sh-syntax)"
  echo "dbus=$DBUS_SESSION_BUS_ADDRESS"
fi

echo "starting web UI..."
uli --ui web --host 127.0.0.1 --port 8787 &
WEB_PID=$!
i=0
while [ "$i" -lt 90 ]; do
  if curl -sf http://127.0.0.1:8787/api/health >/dev/null 2>&1; then
    echo "web UI ready"
    break
  fi
  i=$((i + 1))
  sleep 0.5
done
if ! curl -sf http://127.0.0.1:8787/api/health >/dev/null 2>&1; then
  echo "ERROR: web UI failed to start"
  ps -ef | head -40
  exec xterm -hold -geometry 120x40+40+40 -T "ULI web failed" \
    -e "tail -n 200 /var/log/uli/uli-start.log; echo; exec bash"
fi

# Firefox MUST be started from its install dir (stub uses /proc/self/exe).
if [ -x /opt/firefox/firefox ]; then
  echo "starting Firefox kiosk from /opt/firefox"
  cd /opt/firefox || exit 1
  exec ./firefox \
    --kiosk \
    --new-instance \
    --no-remote \
    "http://127.0.0.1:8787/"
fi

echo "ERROR: /opt/firefox/firefox missing"
exec xterm -hold -e "ls -la /opt/firefox; tail -n 100 /var/log/uli/uli-start.log; bash"
EOF
chmod +x "$CH/usr/local/bin/uli-start"

cat >"$CH/usr/bin/firefox" <<'EOF'
#!/bin/sh
cd /opt/firefox || exit 1
exec ./firefox "$@"
EOF
chmod +x "$CH/usr/bin/firefox"

cat >"$CH/etc/xdg/openbox/autostart" <<'EOF'
#!/bin/sh
xset -dpms 2>/dev/null || true
xset s off 2>/dev/null || true
# Keep a tiny fallback terminal available behind the kiosk if needed
/usr/local/bin/uli-start &
EOF
chmod +x "$CH/etc/xdg/openbox/autostart"

# Quick smoke: firefox --version inside chroot with proc mounted
mount -t proc proc "$CH/proc" 2>/dev/null || true
if chroot "$CH" bash -c 'cd /opt/firefox && ./firefox --version' 2>&1 | tee /tmp/ff-ver.txt; then
  echo "Firefox version OK"
else
  echo "WARN: firefox --version failed (see /tmp/ff-ver.txt)"
fi
umount -l "$CH/proc" 2>/dev/null || true

echo "[boot] GRUB/isolinux auto-boot (no menu wait)..."
mkdir -p "$IMG/isolinux" "$IMG/boot/grub" "$IMG/EFI/BOOT" "$WORK/scratch"
if [ ! -f "$IMG/isolinux/isolinux.bin" ]; then
  cp /usr/lib/ISOLINUX/isolinux.bin "$IMG/isolinux/"
  cp /usr/lib/syslinux/modules/bios/*.c32 "$IMG/isolinux/" 2>/dev/null || true
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

# UEFI GRUB: hide menu, boot immediately
cat >"$IMG/boot/grub/grub.cfg" <<'EOF'
set timeout=0
set timeout_style=hidden
set default=0
insmod all_video
insmod linux
insmod linuxefi
# Keep serial quiet for debugging if attached; no interactive menu
serial --unit=0 --speed=115200
terminal_input console
terminal_output console
menuentry "Ultimate Linux Installer" {
    linux /live/vmlinuz boot=live components quiet splash hostname=uli-live username=uli console=tty0
    initrd /live/initrd.img
}
EOF

# Sync latest web app bits
mkdir -p "$CH/usr/local/lib/python3.10/dist-packages"
rm -rf "$CH/usr/local/lib/python3.10/dist-packages/uli"
cp -a "$ROOT/app/uli" "$CH/usr/local/lib/python3.10/dist-packages/uli"
chown -R uli:uli "$CH/home/uli" "$CH/var/log/uli" 2>/dev/null || true

echo "[squash+iso]..."
rm -f "$IMG/live/filesystem.squashfs" "$ROOT/artifacts"/ultimate-linux-installer-*.iso
mksquashfs "$CH" "$IMG/live/filesystem.squashfs" -comp xz -e boot
if [ ! -f "$IMG/live/vmlinuz" ]; then
  cp "$CH"/boot/vmlinuz-* "$IMG/live/vmlinuz"
  cp "$CH"/boot/initrd.img-* "$IMG/live/initrd.img"
fi
GRUB_EFI_DIR="$(uli_find_grub_efi_dir "$CH")"
BOOT_IMG=$WORK/scratch/efi.img
uli_make_efi_boot_image "$BOOT_IMG" "$IMG" "$LABEL" "$GRUB_EFI_DIR"
cp "$BOOT_IMG" "$IMG/EFI/BOOT/efiboot.img"
uli_xorriso_hybrid "$OUT_ISO" "$LABEL" "$IMG"
ln -sfn "$(basename "$OUT_ISO")" "$ROOT/artifacts/ultimate-linux-installer.iso"
ls -lh "$OUT_ISO"
echo "ISO_READY=$OUT_ISO"
