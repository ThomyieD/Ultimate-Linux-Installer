#!/bin/bash
set -euo pipefail
CH=/var/tmp/uli-iso/chroot

echo "==== autologin groups ===="
grep -E '^(autologin|nopasswdlogin|uli):' "$CH/etc/group" || true
echo "uli groups in passwd/gshadow:"; chroot "$CH" id uli 2>/dev/null || true

echo "==== libqxcb deep deps ===="
PLUGIN=/usr/local/lib/python3.10/dist-packages/PySide6/Qt/plugins/platforms/libqxcb.so
chroot "$CH" ldd "$PLUGIN" | grep -i 'not found' || echo "libqxcb OK"
# common missing on minimal images
for lib in libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
  libxcb-render-util0 libxcb-xinerama0 libxcb-xfixes0 libxcb-shape0 \
  libxcb-randr0 libxcb-render0 libxcb-shm0 libxcb-sync1 libxcb-xkb1 \
  libxkbcommon-x11-0 libdbus-1-3 libfontconfig1 libfreetype6 \
  libegl1 libgl1 libglib2.0-0; do
  if chroot "$CH" dpkg -s "$lib" >/dev/null 2>&1; then
    echo "pkg OK $lib"
  else
    echo "pkg MISSING $lib"
  fi
done

echo "==== try headless Qt start ===="
# install xvfb in chroot if needed on host side for bind
apt-get install -y -qq xvfb xauth >/dev/null 2>&1 || true
# Mount essentials for chroot GUI test
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

# Use host xvfb and chroot with DISPLAY - harder. Run python inside with QT_QPA_PLATFORM=offscreen first.
chroot "$CH" bash -c 'export PYTHONPATH=/usr/local/lib/python3.10/dist-packages; export QT_QPA_PLATFORM=offscreen; timeout 10 python3 -m uli.main --lang de --dry-run' > /tmp/uli-offscreen.log 2>&1 || true
echo "---- offscreen log ----"
cat /tmp/uli-offscreen.log

# Xvfb inside chroot if present
if chroot "$CH" bash -c 'command -v Xvfb >/dev/null' 2>/dev/null; then
  chroot "$CH" bash -c 'export PYTHONPATH=/usr/local/lib/python3.10/dist-packages; export DISPLAY=:99; Xvfb :99 -screen 0 1280x800x24 >/tmp/xvfb.log 2>&1 & sleep 1; timeout 15 /usr/local/bin/uli --lang de --dry-run >/tmp/uli-xvfb.log 2>&1; kill %1 2>/dev/null' || true
  echo "---- xvfb uli log ----"
  cat "$CH/tmp/uli-xvfb.log" 2>/dev/null || cat /tmp/uli-xvfb.log 2>/dev/null || true
else
  echo "no Xvfb in chroot — installing"
  chroot "$CH" apt-get update -qq
  chroot "$CH" apt-get install -y -qq xvfb
  chroot "$CH" bash -c 'export PYTHONPATH=/usr/local/lib/python3.10/dist-packages; export DISPLAY=:99; Xvfb :99 -screen 0 1280x800x24 >/tmp/xvfb.log 2>&1 & sleep 1; timeout 15 /usr/local/bin/uli --lang de --dry-run >/tmp/uli-xvfb.log 2>&1; kill %1 2>/dev/null' || true
  echo "---- xvfb uli log ----"
  cat "$CH/tmp/uli-xvfb.log"
fi
