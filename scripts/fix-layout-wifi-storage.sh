#!/bin/bash
# Layout/WLAN/Storage fixes → ISO 0.2.5 (keeps only newest ISO)
set -euo pipefail
ROOT=/root/Linux-Installer/github/Ultimate-Linux-Installer
CH=/var/tmp/uli-iso/chroot
WORK=/var/tmp/uli-iso
IMG=$WORK/image
VERSION=0.2.5
OUT_ISO=$ROOT/artifacts/ultimate-linux-installer-${VERSION}-amd64.iso
LABEL=ULI_0_2_5
PYSITE=$CH/usr/local/lib/python3.10/dist-packages

source "$ROOT/scripts/lib-iso-uefi.sh"

echo "[1] sync app + adapters..."
mkdir -p "$PYSITE"
rm -rf "$PYSITE/uli" "$PYSITE/adapters"
cp -a "$ROOT/app/uli" "$PYSITE/uli"
cp -a "$ROOT/adapters" "$PYSITE/adapters"

echo "[2] Wi-Fi packages + firmware helpers..."
mount --bind /dev "$CH/dev" 2>/dev/null || true
mount --bind /dev/pts "$CH/dev/pts" 2>/dev/null || true
mount -t proc proc "$CH/proc" 2>/dev/null || true
mount -t sysfs sys "$CH/sys" 2>/dev/null || true
cp /etc/resolv.conf "$CH/etc/resolv.conf" 2>/dev/null || true
chroot "$CH" apt-get update -qq
chroot "$CH" apt-get install -y --no-install-recommends \
  wpasupplicant iw rfkill wireless-tools wireless-regdb \
  network-manager pciutils usbutils \
  linux-firmware \
  util-linux
chroot "$CH" apt-get clean
rm -rf "$CH/var/lib/apt/lists"/* "$CH/tmp"/* "$CH/var/tmp"/*

echo "[2b] refresh uli-start..."
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

if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ] && command -v dbus-launch >/dev/null 2>&1; then
  eval "$(dbus-launch --sh-syntax)"
fi

if command -v vmware-user >/dev/null 2>&1; then
  vmware-user &
elif command -v vmware-user-suid-wrapper >/dev/null 2>&1; then
  vmware-user-suid-wrapper &
fi
sleep 1
if command -v xrandr >/dev/null 2>&1; then
  xrandr --auto 2>/dev/null || true
  for out in Virtual1 Virtual-1 VGA-1 VGA-0 None-1; do
    xrandr --output "$out" --auto 2>/dev/null || true
  done
  xrandr -s 1920x1080 2>/dev/null || xrandr -s 1600x900 2>/dev/null || xrandr -s 1280x800 2>/dev/null || true
fi

# Unblock Wi-Fi (laptops) + bring NetworkManager up
rfkill unblock all 2>/dev/null || true
rfkill unblock wifi 2>/dev/null || true
nmcli networking on 2>/dev/null || true
nmcli radio wifi on 2>/dev/null || true
for w in /sys/class/net/*/wireless; do
  [ -e "$w" ] || continue
  iface=$(basename "$(dirname "$w")")
  nmcli dev set "$iface" managed yes 2>/dev/null || true
done
for dev in $(nmcli -t -f DEVICE,TYPE dev status 2>/dev/null | awk -F: '$2=="ethernet"{print $1}'); do
  nmcli dev set "$dev" managed yes 2>/dev/null || true
  nmcli dev connect "$dev" 2>/dev/null || true
done

echo "starting web UI..."
uli --ui web --host 127.0.0.1 --port 8787 &
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
  exec xterm -hold -geometry 120x40+40+40 -T "ULI web failed" \
    -e "tail -n 200 /var/log/uli/uli-start.log; echo; exec bash"
fi

if [ -x /opt/firefox/firefox ]; then
  echo "starting Firefox kiosk from /opt/firefox"
  cd /opt/firefox || exit 1
  exec ./firefox --kiosk --width=1920 --height=1080 --new-instance --no-remote "http://127.0.0.1:8787/"
fi
echo "ERROR: /opt/firefox/firefox missing"
exec xterm -hold -e "ls -la /opt/firefox; tail -n 100 /var/log/uli/uli-start.log; bash"
EOF
chmod +x "$CH/usr/local/bin/uli-start"

echo "[3] unmount + mountpoints..."
for m in "$CH/dev/pts" "$CH/dev" "$CH/proc" "$CH/sys" "$CH/run"; do
  while mountpoint -q "$m" 2>/dev/null; do
    umount -l "$m" || break
    sleep 0.2
  done
done
if mount | grep -q "$CH/"; then
  echo "ERROR: mounts still present under chroot:" >&2
  mount | grep "$CH/" >&2
  exit 1
fi
mkdir -p "$CH/proc" "$CH/sys" "$CH/dev" "$CH/run/lock" "$CH/tmp" "$CH/boot"
chmod 1777 "$CH/tmp"

# Host Python can't load chroot binary wheels — test imports inside chroot with remounted proc
mount -t proc proc "$CH/proc" 2>/dev/null || true
mount --bind /dev "$CH/dev" 2>/dev/null || true
chroot "$CH" env PYTHONPATH=/usr/local/lib/python3.10/dist-packages python3 - <<'PY'
from uli.core.catalog import catalog_for_mode
from uli.web.server import create_app
assert catalog_for_mode("simple")
app = create_app(simulate_disk=True)
paths = [getattr(r, "path", None) for r in app.routes]
assert "/api/disks" in paths
print("smoke_ok")
PY
umount -l "$CH/proc" 2>/dev/null || true
umount -l "$CH/dev" 2>/dev/null || true

mkdir -p "$IMG/boot/grub" "$IMG/isolinux" "$IMG/EFI/BOOT" "$WORK/scratch"
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

echo "[4] squash + ISO..."
rm -f "$IMG/live/filesystem.squashfs"
rm -f "$ROOT/artifacts"/ultimate-linux-installer-*.iso
rm -f "$ROOT/artifacts"/ultimate-linux-installer.iso
mksquashfs "$CH" "$IMG/live/filesystem.squashfs" -comp xz -e boot
GRUB_EFI_DIR="$(uli_find_grub_efi_dir "$CH")"
BOOT_IMG=$WORK/scratch/efi.img
uli_make_efi_boot_image "$BOOT_IMG" "$IMG" "$LABEL" "$GRUB_EFI_DIR"
cp "$BOOT_IMG" "$IMG/EFI/BOOT/efiboot.img"
uli_xorriso_hybrid "$OUT_ISO" "$LABEL" "$IMG"
ln -sfn "$(basename "$OUT_ISO")" "$ROOT/artifacts/ultimate-linux-installer.iso"
ls -lh "$OUT_ISO"
echo "ISO_READY=$OUT_ISO"
