#!/bin/bash
# Remake squashfs from fixed chroot + rebuild hybrid ISO.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${ULI_ISO_WORK:-/var/tmp/uli-iso}"
CHROOT="$WORK/chroot"
IMG="$WORK/image"
VERSION="${ULI_VERSION:-0.2.0}"
OUT_DIR="$ROOT/artifacts"
OUT_ISO="$OUT_DIR/ultimate-linux-installer-${VERSION}-amd64.iso"
LABEL="ULI_${VERSION//./_}"

# shellcheck source=lib-iso-uefi.sh
source "$ROOT/scripts/lib-iso-uefi.sh"

[ -d "$CHROOT" ] || { echo "missing chroot $CHROOT" >&2; exit 1; }

echo "[1/4] sync app into chroot..."
mkdir -p "$CHROOT/opt/uli/src" "$CHROOT/usr/local/lib/python3.10/dist-packages"
rsync -a --exclude '.git' --exclude '.venv' --exclude 'live-build' \
  --exclude 'artifacts' --exclude 'docs/reference' --exclude '__pycache__' \
  --exclude 'preview' \
  "$ROOT/" "$CHROOT/opt/uli/src/"
rm -rf "$CHROOT/usr/local/lib/python3.10/dist-packages/uli"
cp -a "$CHROOT/opt/uli/src/app/uli" "$CHROOT/usr/local/lib/python3.10/dist-packages/uli"

# Web UI runtime deps + browser
mount --bind /dev "$CHROOT/dev" 2>/dev/null || true
mount --bind /dev/pts "$CHROOT/dev/pts" 2>/dev/null || true
mount -t proc proc "$CHROOT/proc" 2>/dev/null || true
mount -t sysfs sys "$CHROOT/sys" 2>/dev/null || true
cp /etc/resolv.conf "$CHROOT/etc/resolv.conf" 2>/dev/null || true
chroot "$CHROOT" apt-get update -qq
chroot "$CHROOT" apt-get install -y --no-install-recommends curl \
  || true
# Real Firefox binary (Ubuntu firefox package is a useless snap stub in live)
bash "$ROOT/scripts/install-firefox-tarball.sh" "$CHROOT"
chroot "$CHROOT" python3 -m pip install --no-cache-dir fastapi 'uvicorn[standard]' \
  || chroot "$CHROOT" python3 -m pip install --break-system-packages --no-cache-dir \
    fastapi 'uvicorn[standard]'
chroot "$CHROOT" apt-get clean
rm -rf "$CHROOT/var/lib/apt/lists"/* "$CHROOT/tmp"/* "$CHROOT/var/tmp"/*
umount -l "$CHROOT/dev/pts" 2>/dev/null || true
umount -l "$CHROOT/dev" 2>/dev/null || true
umount -l "$CHROOT/proc" 2>/dev/null || true
umount -l "$CHROOT/sys" 2>/dev/null || true

cat >"$CHROOT/usr/local/bin/uli" <<'EOF'
#!/bin/sh
export PYTHONPATH=/usr/local/lib/python3.10/dist-packages${PYTHONPATH:+:$PYTHONPATH}
exec python3 -m uli.main "$@"
EOF
chmod +x "$CHROOT/usr/local/bin/uli"

cat >"$CHROOT/usr/local/bin/uli-start" <<'EOF'
#!/bin/sh
export PYTHONPATH=/usr/local/lib/python3.10/dist-packages
export ULI_SIMULATE_DISK=0
export ULI_DRY_RUN=0
mkdir -p /var/log/uli
exec >>/var/log/uli/uli-start.log 2>&1
echo "==== $(date -Is) DISPLAY=$DISPLAY ===="

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

if command -v firefox >/dev/null 2>&1; then
  exec firefox --kiosk --new-instance "http://127.0.0.1:8787/"
fi
if command -v uli-firefox >/dev/null 2>&1; then
  exec uli-firefox --kiosk --new-instance "http://127.0.0.1:8787/"
fi
if [ -x /opt/firefox/firefox ]; then
  exec /opt/firefox/firefox --kiosk --new-instance "http://127.0.0.1:8787/"
fi
if command -v firefox-esr >/dev/null 2>&1; then
  exec firefox-esr --kiosk --new-instance "http://127.0.0.1:8787/"
fi

echo "No browser found — web UI on :8787 (pid $WEB_PID)"
xterm -hold -e "echo ULI web UI: http://127.0.0.1:8787; tail -f /var/log/uli/uli-start.log" &
wait "$WEB_PID"
EOF
chmod +x "$CHROOT/usr/local/bin/uli-start"

mkdir -p "$CHROOT/home/uli/.config/openbox" "$CHROOT/etc/xdg/openbox" \
  "$CHROOT/etc/xdg/autostart" "$CHROOT/etc/lightdm" "$CHROOT/var/log/uli"
rm -f "$CHROOT/home/uli/.config/openbox/autostart" "$CHROOT/etc/xdg/autostart/uli.desktop"
cat >"$CHROOT/etc/xdg/openbox/autostart" <<'EOF'
#!/bin/sh
xset -dpms 2>/dev/null || true
xset s off 2>/dev/null || true
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
chroot "$CHROOT" gpasswd -a uli autologin || true
chroot "$CHROOT" gpasswd -a uli nopasswdlogin || true
chroot "$CHROOT" chown -R uli:uli /home/uli /var/log/uli

echo "[2/4] rebuild squashfs..."
rm -f "$IMG/live/filesystem.squashfs"
# Ensure kernel/initrd present
if [ ! -f "$IMG/live/vmlinuz" ]; then
  cp "$CHROOT"/boot/vmlinuz-* "$IMG/live/vmlinuz"
  cp "$CHROOT"/boot/initrd.img-* "$IMG/live/initrd.img"
fi
mksquashfs "$CHROOT" "$IMG/live/filesystem.squashfs" -comp xz -e boot

echo "[3/4] UEFI + BIOS boot files..."
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
GRUB_EFI_DIR="$(uli_find_grub_efi_dir "$CHROOT")"
BOOT_IMG="$WORK/scratch/efi.img"
uli_make_efi_boot_image "$BOOT_IMG" "$IMG" "$LABEL" "$GRUB_EFI_DIR"
cp "$BOOT_IMG" "$IMG/EFI/BOOT/efiboot.img"

echo "[4/4] hybrid ISO..."
mkdir -p "$OUT_DIR"
rm -f "$OUT_DIR"/ultimate-linux-installer-*-amd64.iso "$OUT_DIR"/ultimate-linux-installer.iso
uli_xorriso_hybrid "$OUT_ISO" "$LABEL" "$IMG"
ln -sfn "$(basename "$OUT_ISO")" "$OUT_DIR/ultimate-linux-installer.iso"
ls -lh "$OUT_ISO"
echo "ISO_READY=$OUT_ISO"
