#!/usr/bin/env bash
# Reproducible Ubuntu Noble based UEFI/BIOS live image for ULI.
set -euo pipefail
umask 022

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${ULI_ISO_WORK:-/var/tmp/uli-iso-build}"
ARCH=amd64
DIST=noble
MIRROR="${ULI_MIRROR:-https://archive.ubuntu.com/ubuntu}"
OUT_DIR="$ROOT/artifacts"
VERSION="${ULI_VERSION:-0.3.0}"
OUT_ISO="$OUT_DIR/ultimate-linux-installer-${VERSION}-amd64.iso"
LABEL="ULI_${VERSION//./_}"

export DEBIAN_FRONTEND=noninteractive

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this ISO builder as root (sudo)." >&2
  exit 2
fi
WORK_PARENT="$(dirname "$WORK")"
mkdir -p "$WORK_PARENT"
WORK_PARENT="$(realpath -e "$WORK_PARENT")"
WORK="$WORK_PARENT/$(basename "$WORK")"
if [[ "$WORK_PARENT" != "/var/tmp" || ! "$(basename "$WORK")" =~ ^uli-iso-[A-Za-z0-9._-]+$ ]]; then
  echo "Refusing unsafe ULI_ISO_WORK path: $WORK" >&2
  exit 2
fi
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9]+)*$ ]]; then
  echo "Invalid ULI_VERSION: $VERSION" >&2
  exit 2
fi
APP_VERSION="$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$ROOT/pyproject.toml" | head -n1)"
if [ "$VERSION" != "$APP_VERSION" ]; then
  echo "ULI_VERSION $VERSION does not match application version $APP_VERSION" >&2
  exit 2
fi

need() {
  command -v "$1" >/dev/null || {
    echo "Missing build dependency: $1" >&2
    exit 1
  }
}
for tool in debootstrap mksquashfs xorriso rsync mkfs.vfat grub-mkimage \
  sha256sum curl dpkg-deb gpg; do
  need "$tool"
done

rm -rf -- "$WORK"
mkdir -p "$WORK"/{chroot,image/{live,boot/grub,EFI/BOOT},scratch}
CHROOT="$WORK/chroot"
IMG="$WORK/image"

cleanup() {
  local mountpoint
  for mountpoint in run dev/pts dev proc sys; do
    while mountpoint -q "$CHROOT/$mountpoint" 2>/dev/null; do
      umount -l "$CHROOT/$mountpoint" 2>/dev/null || break
    done
  done
}
trap cleanup EXIT

echo "[1/7] Bootstrap Ubuntu $DIST..."
debootstrap --arch="$ARCH" --variant=minbase "$DIST" "$CHROOT" "$MIRROR"

echo "[2/7] Install live runtime and installer tools..."
cat >"$CHROOT/etc/apt/sources.list" <<EOF
deb $MIRROR $DIST main restricted universe multiverse
deb $MIRROR $DIST-updates main restricted universe multiverse
deb $MIRROR $DIST-security main restricted universe multiverse
EOF
cp -L /etc/resolv.conf "$CHROOT/etc/resolv.conf"
mount --bind /dev "$CHROOT/dev"
mount --bind /dev/pts "$CHROOT/dev/pts"
mount -t proc proc "$CHROOT/proc"
mount -t sysfs sysfs "$CHROOT/sys"
mount --bind /run "$CHROOT/run"

chroot "$CHROOT" apt-get update
chroot "$CHROOT" apt-get install -y --no-install-recommends \
  linux-image-generic live-boot live-config live-config-systemd live-tools \
  systemd-sysv sudo locales tzdata \
  network-manager wpasupplicant iw rfkill wireless-regdb linux-firmware \
  ca-certificates curl wget gnupg gpgv openssl \
  xorg openbox lightdm lightdm-gtk-greeter dbus-x11 xterm \
  open-vm-tools open-vm-tools-desktop spice-vdagent \
  xserver-xorg-core xserver-xorg-input-libinput \
  xserver-xorg-video-vesa xserver-xorg-video-fbdev xserver-xorg-video-vmware \
  libgtk-3-0t64 libdbus-glib-1-2 libasound2t64 libx11-xcb1 libxt6t64 \
  python3 python3-venv python3-pip \
  debootstrap ubuntu-keyring debian-archive-keyring \
  gdisk parted dosfstools e2fsprogs btrfs-progs xfsprogs \
  util-linux lvm2 cryptsetup \
  efibootmgr grub-efi-amd64-bin grub-pc-bin grub2-common shim-signed \
  squashfs-tools rsync fonts-dejavu-core pciutils usbutils \
  isolinux syslinux-common policykit-1

# Ubuntu's minimal NetworkManager package deliberately excludes Ethernet from
# global management.  The live environment instead needs every wired/Wi-Fi
# NIC managed, plus a name-independent DHCP profile that can autoconnect on
# more than one wired adapter.  NetworkManager rejects insecure keyfiles, so
# ownership and modes are set explicitly here rather than inherited from git.
install -D -o root -g root -m 0644 \
  "$ROOT/assets/networkmanager/99-uli-live-network.conf" \
  "$CHROOT/etc/NetworkManager/conf.d/99-uli-live-network.conf"
install -D -o root -g root -m 0600 \
  "$ROOT/assets/networkmanager/uli-wired-dhcp.nmconnection" \
  "$CHROOT/etc/NetworkManager/system-connections/uli-wired-dhcp.nmconnection"

echo "uli-live" >"$CHROOT/etc/hostname"
chroot "$CHROOT" update-initramfs -u

echo "[3/7] Install ULI application and browser..."
bash "$ROOT/scripts/generate-theme-assets.sh"
# shellcheck source=scripts/lib-runtime-bundle.sh
source "$ROOT/scripts/lib-runtime-bundle.sh"
uli_install_runtime_bundle "$ROOT" "$CHROOT" root:root

chroot "$CHROOT" python3 -m venv /opt/uli/venv
chroot "$CHROOT" /opt/uli/venv/bin/pip install --no-cache-dir \
  --disable-pip-version-check /opt/uli/src
# setuptools creates build/ and *.egg-info inside the source tree while
# building the wheel.  Refresh the allowlisted bundle after installation so
# those development artifacts cannot leak into the live image.
uli_install_runtime_bundle "$ROOT" "$CHROOT" root:root
uli_harden_runtime_bundle "$CHROOT" root:root
bash "$ROOT/scripts/install-firefox-tarball.sh" "$CHROOT"
install -D -m 0644 "$ROOT/assets/firefox/policies.json" \
  "$CHROOT/opt/firefox/distribution/policies.json"
chroot "$CHROOT" /opt/firefox/firefox --headless --version >/dev/null

cat >"$CHROOT/usr/local/bin/uli" <<'EOF'
#!/bin/sh
export PYTHONPATH=/opt/uli${PYTHONPATH:+:$PYTHONPATH}
exec /opt/uli/venv/bin/python -m uli.main "$@"
EOF
chmod 755 "$CHROOT/usr/local/bin/uli"

# The backend owns the destructive operations and therefore runs as root.  The
# kiosk browser remains an unprivileged user; no blanket sudo rule is needed.
cat >"$CHROOT/etc/systemd/system/uli-web.service" <<'EOF'
[Unit]
Description=Ultimate Linux Installer backend
After=NetworkManager.service
Wants=NetworkManager.service

[Service]
Type=simple
User=root
Group=root
UMask=0077
WorkingDirectory=/var/lib/uli
Environment=PYTHONPATH=/opt/uli
Environment=ULI_SIMULATE_DISK=0
Environment=ULI_DRY_RUN=0
ExecStart=/usr/local/bin/uli --ui web --host 127.0.0.1 --port 8787
Restart=on-failure
RestartSec=2

[Install]
WantedBy=graphical.target
EOF

cat >"$CHROOT/usr/local/bin/uli-start" <<'EOF'
#!/bin/sh
set -eu
mkdir -p "$HOME/.mozilla"
xset -dpms 2>/dev/null || true
xset s off 2>/dev/null || true
if command -v vmware-user >/dev/null 2>&1; then vmware-user & fi
if command -v spice-vdagent >/dev/null 2>&1; then spice-vdagent & fi
xrandr --auto 2>/dev/null || true

i=0
while [ "$i" -lt 120 ]; do
  if curl -fsS http://127.0.0.1:8787/api/health >/dev/null 2>&1; then break; fi
  i=$((i + 1))
  sleep 0.5
done
if ! curl -fsS http://127.0.0.1:8787/api/health >/dev/null 2>&1; then
  exec xterm -hold -T "ULI backend failed" -e \
    "echo 'Installer backend failed to start.'; systemctl status uli-web; journalctl -u uli-web -n 100"
fi
exec /opt/firefox/firefox --kiosk --new-instance --no-remote http://127.0.0.1:8787/
EOF
chmod 755 "$CHROOT/usr/local/bin/uli-start"

cat >"$CHROOT/usr/local/bin/uli-boot-marker" <<'EOF'
#!/bin/sh
set -eu
i=0
while [ "$i" -lt 120 ]; do
  if curl -fsS http://127.0.0.1:8787/api/health >/dev/null 2>&1; then
    printf 'ULI_LIVE_READY\n' >/dev/ttyS0 2>/dev/null || true
    exit 0
  fi
  i=$((i + 1))
  sleep 0.5
done
exit 1
EOF
chmod 755 "$CHROOT/usr/local/bin/uli-boot-marker"

cat >"$CHROOT/etc/systemd/system/uli-boot-marker.service" <<'EOF'
[Unit]
Description=Ultimate Linux Installer boot verification marker
After=uli-web.service
Requires=uli-web.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/uli-boot-marker

[Install]
WantedBy=graphical.target
EOF

mkdir -p "$CHROOT/etc/xdg/openbox" "$CHROOT/etc/lightdm" \
  "$CHROOT/etc/live/config.conf.d" "$CHROOT/var/lib/uli" "$CHROOT/var/cache/uli"
cat >"$CHROOT/etc/xdg/openbox/autostart" <<'EOF'
#!/bin/sh
/usr/local/bin/uli-start &
EOF
chmod 755 "$CHROOT/etc/xdg/openbox/autostart"
cat >"$CHROOT/etc/lightdm/lightdm.conf" <<'EOF'
[Seat:*]
autologin-user=uli
autologin-user-timeout=0
user-session=openbox
greeter-session=lightdm-gtk-greeter
EOF

chroot "$CHROOT" groupadd -f autologin
chroot "$CHROOT" groupadd -f nopasswdlogin
chroot "$CHROOT" useradd -m -G audio,video,netdev,autologin,nopasswdlogin -s /bin/bash uli 2>/dev/null || \
  chroot "$CHROOT" usermod -aG audio,video,netdev,autologin,nopasswdlogin uli
echo 'uli:uli' | chroot "$CHROOT" chpasswd
chroot "$CHROOT" chown -R root:root /var/lib/uli /var/cache/uli
chroot "$CHROOT" chmod 700 /var/lib/uli /var/cache/uli
chroot "$CHROOT" systemctl enable NetworkManager.service lightdm.service \
  uli-web.service uli-boot-marker.service
cat >"$CHROOT/etc/live/config.conf.d/uli.conf" <<'EOF'
LIVE_USERNAME="uli"
LIVE_USER_DEFAULT_GROUPS="audio cdrom dip video plugdev netdev"
EOF

echo "[4/7] Pin Debian archive keyring and pack squashfs..."
# Replace the Ubuntu-packaged debian-archive-keyring (often too old for Debian 13)
# with the version-pinned upstream artefact.  Maintainer scripts are never run.
# The helper is linted via release-iso.yml; check.sh does not yet list it (TASK-001 scope).
# shellcheck disable=SC1091
# shellcheck source=scripts/lib-debian-archive-keyring.sh
source "$ROOT/scripts/lib-debian-archive-keyring.sh"
KEYRING_WORK="$WORK/scratch/debian-archive-keyring"
mkdir -p "$KEYRING_WORK"
uli_debian_archive_keyring_install_into_chroot "$CHROOT" "$KEYRING_WORK"

chroot "$CHROOT" apt-get clean
rm -rf "$CHROOT/var/lib/apt/lists"/* "$CHROOT/tmp"/* "$CHROOT/var/tmp"/*
# ``debootstrap`` needs the build host's resolver, but preserving that regular
# file in the squashfs leaves the live image with stale DNS servers.  At boot
# NetworkManager owns this target and rewrites it after DHCP/Wi-Fi connects.
rm -f "$CHROOT/etc/resolv.conf"
ln -s ../run/NetworkManager/resolv.conf "$CHROOT/etc/resolv.conf"
cleanup
trap - EXIT
if mount | grep -Fq "$CHROOT/"; then
  echo "Refusing to pack active chroot mounts:" >&2
  mount | grep -F "$CHROOT/" >&2
  exit 1
fi
uli_verify_runtime_bundle_security "$CHROOT"
# Fail closed before squashfs if Debian 13 trust anchors are incomplete.
uli_debian_archive_keyring_verify_installed "$CHROOT"
mksquashfs "$CHROOT" "$IMG/live/filesystem.squashfs" -comp xz -e boot

kernel="$(find "$CHROOT/boot" -maxdepth 1 -name 'vmlinuz-*' -type f | sort -V | tail -n1)"
initrd="$(find "$CHROOT/boot" -maxdepth 1 -name 'initrd.img-*' -type f | sort -V | tail -n1)"
test -n "$kernel" -a -n "$initrd"
cp "$kernel" "$IMG/live/vmlinuz"
cp "$initrd" "$IMG/live/initrd.img"

echo "[5/7] Create BIOS and UEFI boot images..."
mkdir -p "$IMG/isolinux"
if [ -f /usr/lib/ISOLINUX/isolinux.bin ]; then
  cp /usr/lib/ISOLINUX/isolinux.bin "$IMG/isolinux/"
  cp /usr/lib/syslinux/modules/bios/*.c32 "$IMG/isolinux/"
else
  cp "$CHROOT/usr/lib/ISOLINUX/isolinux.bin" "$IMG/isolinux/"
  cp "$CHROOT/usr/lib/syslinux/modules/bios/"*.c32 "$IMG/isolinux/"
fi
cat >"$IMG/isolinux/isolinux.cfg" <<'EOF'
UI menu.c32
PROMPT 0
TIMEOUT 10
DEFAULT uli
LABEL uli
  MENU LABEL Ultimate Linux Installer
  KERNEL /live/vmlinuz
  APPEND initrd=/live/initrd.img boot=live components quiet splash hostname=uli-live username=uli
EOF

# shellcheck source=scripts/lib-iso-uefi.sh
source "$ROOT/scripts/lib-iso-uefi.sh"
cat >"$IMG/boot/grub/grub.cfg" <<'EOF'
set timeout=1
set timeout_style=hidden
set default=0
insmod all_video
insmod linux
insmod serial
serial --unit=0 --speed=115200 --word=8 --parity=no --stop=1
terminal_input console serial
terminal_output console serial
menuentry "Ultimate Linux Installer" {
    linux /live/vmlinuz boot=live components quiet splash hostname=uli-live username=uli console=tty0 console=ttyS0,115200n8
    initrd /live/initrd.img
}
EOF
GRUB_EFI_DIR="$(uli_find_grub_efi_dir "$CHROOT")" || {
  echo "GRUB EFI modules not found" >&2
  exit 1
}
BOOT_IMG="$WORK/scratch/efi.img"
uli_make_efi_boot_image "$BOOT_IMG" "$IMG" "$LABEL" "$GRUB_EFI_DIR"
cp "$BOOT_IMG" "$IMG/EFI/BOOT/efiboot.img"

echo "[6/7] Create hybrid ISO..."
mkdir -p "$OUT_DIR"
rm -f "$OUT_ISO"
uli_xorriso_hybrid "$OUT_ISO" "$LABEL" "$IMG"
ln -sfn "$(basename "$OUT_ISO")" "$OUT_DIR/ultimate-linux-installer.iso"

echo "[7/7] Write checksum..."
(cd "$OUT_DIR" && sha256sum "$(basename "$OUT_ISO")" >SHA256SUMS)
ls -lh "$OUT_ISO" "$OUT_DIR/SHA256SUMS"
echo "ISO_READY=$OUT_ISO"
