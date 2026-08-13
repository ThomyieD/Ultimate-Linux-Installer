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
chroot "$CH" apt-get update -qq
chroot "$CH" apt-get install -y --no-install-recommends \
  libxcb-icccm4 libxcb-keysyms1 libxcb-xinerama0 libxcb-xkb1 \
  libxkbcommon-x11-0 libxcb-cursor0 libxcb-util1 \
  fonts-dejavu-core xterm \
  xvfb

# LightDM autologin group
chroot "$CH" groupadd -f autologin
chroot "$CH" groupadd -f nopasswdlogin
chroot "$CH" gpasswd -a uli autologin
chroot "$CH" gpasswd -a uli nopasswdlogin
chroot "$CH" chown -R uli:uli /home/uli
mkdir -p "$CH/home/uli/.config/openbox" "$CH/var/log/uli"
chroot "$CH" chown -R uli:uli /home/uli /var/log/uli

# Robust starter with logfile
cat >"$CH/usr/local/bin/uli-start" <<'EOF'
#!/bin/sh
export PYTHONPATH=/usr/local/lib/python3.10/dist-packages
export ULI_SIMULATE_DISK=0
export ULI_DRY_RUN=0
export QT_QPA_PLATFORM=xcb
export QT_XCB_GL_INTEGRATION=none
mkdir -p /var/log/uli /home/uli/.config/openbox
exec >>/var/log/uli/uli-start.log 2>&1
echo "==== $(date -Is) DISPLAY=$DISPLAY USER=$(id) ===="
# Keep a terminal available if the GUI dies
xterm -geometry 100x30+20+20 -T "ULI debug" -e "tail -f /var/log/uli/uli-start.log" &
sleep 1
echo "starting uli..."
exec /usr/local/bin/uli --lang de
EOF
chmod +x "$CH/usr/local/bin/uli-start"

cat >"$CH/home/uli/.config/openbox/autostart" <<'EOF'
#!/bin/sh
/usr/local/bin/uli-start &
EOF
chmod +x "$CH/home/uli/.config/openbox/autostart"
chroot "$CH" chown -R uli:uli /home/uli

cat >"$CH/etc/xdg/openbox/autostart" <<'EOF'
#!/bin/sh
/usr/local/bin/uli-start &
EOF
chmod +x "$CH/etc/xdg/openbox/autostart"

# Ensure lightdm autologin
cat >"$CH/etc/lightdm/lightdm.conf" <<'EOF'
[Seat:*]
autologin-user=uli
autologin-user-timeout=0
user-session=openbox
greeter-session=lightdm-gtk-greeter
EOF

echo "==== retest xvfb ===="
chroot "$CH" bash -c 'export PYTHONPATH=/usr/local/lib/python3.10/dist-packages; export DISPLAY=:99; rm -f /tmp/.X99-lock; Xvfb :99 -screen 0 1280x800x24 >/tmp/xvfb.log 2>&1 & XV=$!; sleep 1; timeout 12 python3 -m uli.main --lang de --dry-run >/tmp/uli-xvfb2.log 2>&1; RC=$?; kill $XV 2>/dev/null; echo RC=$RC; tail -50 /tmp/uli-xvfb2.log'
