#!/bin/bash
# Network robustness + open-vm-tools for VMware Workstation testing.
set -euo pipefail
ROOT=/root/Linux-Installer/github/Ultimate-Linux-Installer
CH=/var/tmp/uli-iso/chroot
WORK=/var/tmp/uli-iso
IMG=$WORK/image
VERSION=0.2.3
OUT_ISO=$ROOT/artifacts/ultimate-linux-installer-${VERSION}-amd64.iso
LABEL=ULI_0_2_3

# shellcheck source=lib-iso-uefi.sh
source "$ROOT/scripts/lib-iso-uefi.sh"

echo "[1] sync app..."
rm -rf "$CH/usr/local/lib/python3.10/dist-packages/uli"
cp -a "$ROOT/app/uli" "$CH/usr/local/lib/python3.10/dist-packages/uli"
rm -rf "$CH/usr/local/lib/python3.10/dist-packages/adapters"
cp -a "$ROOT/adapters" "$CH/usr/local/lib/python3.10/dist-packages/adapters"

echo "[2] packages: open-vm-tools + NM helpers..."
mount --bind /dev "$CH/dev" 2>/dev/null || true
mount --bind /dev/pts "$CH/dev/pts" 2>/dev/null || true
mount -t proc proc "$CH/proc" 2>/dev/null || true
mount -t sysfs sys "$CH/sys" 2>/dev/null || true
cp /etc/resolv.conf "$CH/etc/resolv.conf" 2>/dev/null || true
chroot "$CH" apt-get update -qq
chroot "$CH" apt-get install -y --no-install-recommends \
  open-vm-tools open-vm-tools-desktop \
  xserver-xorg-video-vmware \
  network-manager isc-dhcp-client dnsutils iproute2 \
  curl
chroot "$CH" systemctl enable open-vm-tools.service 2>/dev/null || true
chroot "$CH" systemctl enable vgauth.service 2>/dev/null || true
chroot "$CH" systemctl enable NetworkManager.service 2>/dev/null || true

# Make sure NM manages virtual/ethernet NICs (VMware, KVM, bare metal)
mkdir -p "$CH/etc/NetworkManager/conf.d"
cat >"$CH/etc/NetworkManager/conf.d/10-uli-manage-all.conf" <<'EOF'
[main]
plugins=ifupdown,keyfile

[ifupdown]
managed=true

[keyfile]
unmanaged-devices=none
EOF

# Prefer DHCP on ethernet automatically
mkdir -p "$CH/etc/NetworkManager/system-connections"
cat >"$CH/etc/NetworkManager/system-connections/uli-ethernet.nmconnection" <<'EOF'
[connection]
id=uli-ethernet
uuid=a1b2c3d4-e5f6-7890-abcd-ef1234567890
type=ethernet
autoconnect=true
autoconnect-priority=100

[ethernet]

[ipv4]
method=auto

[ipv6]
method=auto
EOF
chmod 600 "$CH/etc/NetworkManager/system-connections/uli-ethernet.nmconnection"

chroot "$CH" apt-get clean
rm -rf "$CH/var/lib/apt/lists"/* "$CH/tmp"/* "$CH/var/tmp"/*
# Critical: never squash live mounts (causes mksquashfs infinite read loops)
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
# Empty mountpoints must exist in the squashfs (live-boot mounts over them)
mkdir -p "$CH/proc" "$CH/sys" "$CH/dev" "$CH/run/lock" "$CH/tmp" "$CH/boot"
chmod 1777 "$CH/tmp"

echo "[3] uli-start with VMware display helpers..."
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

# VMware: start user agent for resolution sync (open-vm-tools-desktop)
if command -v vmware-user >/dev/null 2>&1; then
  vmware-user &
elif command -v vmware-user-suid-wrapper >/dev/null 2>&1; then
  vmware-user-suid-wrapper &
fi
sleep 1
# Nudge a usable resolution if guest tools / xrandr are available
if command -v xrandr >/dev/null 2>&1; then
  xrandr --auto 2>/dev/null || true
  # Common VMware output names
  for out in Virtual1 Virtual-1 VGA-1 VGA-0 None-1; do
    xrandr --output "$out" --auto 2>/dev/null || true
  done
  # Prefer something readable in Workstation window
  xrandr -s 1920x1080 2>/dev/null || xrandr -s 1600x900 2>/dev/null || xrandr -s 1280x800 2>/dev/null || true
fi

# Kick NetworkManager / DHCP early (bridged VMs + LAN)
nmcli networking on 2>/dev/null || true
for dev in $(nmcli -t -f DEVICE,TYPE dev status 2>/dev/null | awk -F: '$2=="ethernet"{print $1}'); do
  nmcli dev set "$dev" managed yes 2>/dev/null || true
  nmcli dev connect "$dev" 2>/dev/null || true
done

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
  exec xterm -hold -geometry 120x40+40+40 -T "ULI web failed" \
    -e "tail -n 200 /var/log/uli/uli-start.log; echo; exec bash"
fi

if [ -x /opt/firefox/firefox ]; then
  echo "starting Firefox kiosk from /opt/firefox"
  cd /opt/firefox || exit 1
  exec ./firefox --kiosk --new-instance --no-remote "http://127.0.0.1:8787/"
fi
echo "ERROR: /opt/firefox/firefox missing"
exec xterm -hold -e "ls -la /opt/firefox; tail -n 100 /var/log/uli/uli-start.log; bash"
EOF
chmod +x "$CH/usr/local/bin/uli-start"

cat >"$CH/etc/xdg/openbox/autostart" <<'EOF'
#!/bin/sh
xset -dpms 2>/dev/null || true
xset s off 2>/dev/null || true
/usr/local/bin/uli-start &
EOF
chmod +x "$CH/etc/xdg/openbox/autostart"

# Keep GRUB auto-boot
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
rm -f "$IMG/live/filesystem.squashfs" "$ROOT/artifacts"/ultimate-linux-installer-*.iso
# Only exclude /boot (kernel lives on ISO). Keep empty proc/sys/dev/run/tmp mountpoints!
mksquashfs "$CH" "$IMG/live/filesystem.squashfs" -comp xz -e boot
GRUB_EFI_DIR="$(uli_find_grub_efi_dir "$CH")"
BOOT_IMG=$WORK/scratch/efi.img
uli_make_efi_boot_image "$BOOT_IMG" "$IMG" "$LABEL" "$GRUB_EFI_DIR"
cp "$BOOT_IMG" "$IMG/EFI/BOOT/efiboot.img"
uli_xorriso_hybrid "$OUT_ISO" "$LABEL" "$IMG"
ln -sfn "$(basename "$OUT_ISO")" "$ROOT/artifacts/ultimate-linux-installer.iso"
ls -lh "$OUT_ISO"
echo "ISO_READY=$OUT_ISO"
