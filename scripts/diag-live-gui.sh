#!/bin/bash
set -euo pipefail
CH=/var/tmp/uli-iso/chroot
echo "==== owners ===="
ls -ln "$CH/home/uli"
awk -F: '/^uli:/{print "uli passwd:",$0}' "$CH/etc/passwd"
echo "==== groups ===="
grep -E '^(uli|autologin|nopasswdlogin):' "$CH/etc/group" || true
grep -n autologin "$CH/etc/pam.d/lightdm"* 2>/dev/null || true
echo "==== pyside/uli import ===="
chroot "$CH" python3 -c 'import PySide6; print("PySide6", PySide6.__version__)'
chroot "$CH" python3 -c 'import uli.main; print("uli import ok")'
chroot "$CH" python3 -c 'from PySide6.QtWidgets import QApplication; print("QtWidgets ok")'
echo "==== qt/xcb libs ===="
chroot "$CH" bash -c 'ldconfig -p | grep -iE "libQt6Core|libGL\.|libEGL|libxcb\.|libxkbcommon" | head -40'
echo "==== platforms plugin ===="
find "$CH/usr" -path '*Qt*plugins*platforms*' 2>/dev/null | head
find "$CH" -name 'libqxcb.so' 2>/dev/null | head
echo "==== squashfs home ===="
mkdir -p /tmp/uli-sq
umount /tmp/uli-sq 2>/dev/null || true
mount -o loop,ro /var/tmp/uli-iso/image/live/filesystem.squashfs /tmp/uli-sq
ls -ln /tmp/uli-sq/home/uli
chroot /tmp/uli-sq python3 -c 'import PySide6, uli.main; print("squash ok", PySide6.__version__)' || echo "squash import FAIL"
# check missing runtime deps via ldd on Qt
PLUGIN=$(find /tmp/uli-sq -name 'libqxcb.so' 2>/dev/null | head -1)
echo "plugin=$PLUGIN"
if [ -n "$PLUGIN" ]; then
  chroot /tmp/uli-sq ldd "${PLUGIN#/tmp/uli-sq}" | grep -i 'not found' || echo "no missing ldd deps on libqxcb"
fi
umount /tmp/uli-sq
echo DONE
