#!/bin/bash
set -euo pipefail
CH=/var/tmp/uli-iso/chroot
mount --bind /dev "$CH/dev" 2>/dev/null || true
mount --bind /dev/pts "$CH/dev/pts" 2>/dev/null || true
mount -t proc proc "$CH/proc" 2>/dev/null || true
mount -t sysfs sys "$CH/sys" 2>/dev/null || true
cleanup() {
  umount -l "$CH/dev/pts" 2>/dev/null || true
  umount -l "$CH/dev" 2>/dev/null || true
  umount -l "$CH/proc" 2>/dev/null || true
  umount -l "$CH/sys" 2>/dev/null || true
}
trap cleanup EXIT

cp /etc/resolv.conf "$CH/etc/resolv.conf"
echo uli-live >"$CH/etc/hostname"
cat >"$CH/etc/hosts" <<'EOF'
127.0.0.1 localhost
127.0.1.1 uli-live
::1 localhost ip6-localhost ip6-loopback
EOF

chroot "$CH" apt-get update -qq
chroot "$CH" apt-get install -y --no-install-recommends \
  live-config live-config-systemd live-tools \
  xserver-xorg-core xserver-xorg-input-libinput \
  xserver-xorg-video-vesa xserver-xorg-video-fbdev \
  xserver-xorg-video-all \
  dbus-x11 policykit-1 \
  libxcb-icccm4 libxcb-keysyms1 libxcb-xinerama0 libxcb-xkb1 \
  libxkbcommon-x11-0 libxcb-cursor0 libxcb-util1 \
  locales

chroot "$CH" bash -c 'echo "en_US.UTF-8 UTF-8" >/etc/locale.gen; echo "de_DE.UTF-8 UTF-8" >>/etc/locale.gen; locale-gen'
chroot "$CH" update-locale LANG=de_DE.UTF-8 || true

# live-config: autologin user
mkdir -p "$CH/etc/live/config.conf.d"
cat >"$CH/etc/live/config.conf.d/uli.conf" <<'EOF'
LIVE_USERNAME="uli"
LIVE_USER_FULLNAME="Ultimate Linux Installer"
LIVE_USER_DEFAULT_GROUPS="audio cdrom dip floppy video plugdev netdev sudo autologin nopasswdlogin"
LIVE_HOSTNAME="uli-live"
LIVE_LOCALES="de_DE.UTF-8"
LIVE_TIMEZONE="Europe/Berlin"
LIVE_KEYBOARD_LAYOUTS="de"
LIVE_KEYBOARD_MODEL="pc105"
EOF

chroot "$CH" groupadd -f autologin
chroot "$CH" groupadd -f nopasswdlogin
chroot "$CH" usermod -aG sudo,audio,video,netdev,autologin,nopasswdlogin uli || true
chroot "$CH" chown -R uli:uli /home/uli /var/log/uli

# Ensure lightdm can start without waiting forever on Plymouth
mkdir -p "$CH/etc/systemd/system/lightdm.service.d"
cat >"$CH/etc/systemd/system/lightdm.service.d/override.conf" <<'EOF'
[Service]
ExecStartPre=
EOF

chroot "$CH" apt-get clean
rm -rf "$CH/var/lib/apt/lists"/* "$CH/tmp"/* "$CH/var/tmp"/*

echo "==== confirm xcb + video ===="
chroot "$CH" dpkg -l libxkbcommon-x11-0 libxcb-xkb1 xserver-xorg-video-vesa live-config | grep ^ii
chroot "$CH" bash -c 'export PYTHONPATH=/usr/local/lib/python3.10/dist-packages QT_QPA_PLATFORM=xcb DISPLAY=:99
Xvfb :99 -screen 0 1024x768x24 >/tmp/xvfb.log 2>&1 & XV=$!
sleep 1
timeout 8 python3 -m uli.main --lang de --dry-run >/tmp/uli.log 2>&1
RC=$?
kill $XV 2>/dev/null
echo RC=$RC
tail -20 /tmp/uli.log'
