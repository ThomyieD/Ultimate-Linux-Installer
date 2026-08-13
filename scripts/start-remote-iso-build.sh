#!/bin/bash
set -e
cd /root/Linux-Installer/github/Ultimate-Linux-Installer
git fetch origin
git reset --hard origin/main
find scripts live-build/config/hooks -type f \( -name '*.sh' -o -name '*.hook.chroot' \) -exec sed -i 's/\r$//' {} +
chmod +x scripts/*.sh live-build/config/hooks/normal/*.hook.chroot
if head -1 scripts/build-iso.sh | grep -q $'\r'; then
  echo "CRLF still present" >&2
  exit 1
fi
pkill -f 'lb build' >/dev/null 2>&1 || true
pkill -f 'build-iso.sh' >/dev/null 2>&1 || true
sleep 1
rm -f /root/uli-iso-build.log
nohup ./scripts/build-iso.sh >/root/uli-iso-build.log 2>&1 &
echo "BUILD_PID=$!"
sleep 8
tail -n 40 /root/uli-iso-build.log
