#!/bin/bash
set -euo pipefail
CH=/var/tmp/uli-iso/chroot
echo "==== firefox ldd missing ===="
chroot "$CH" bash -c 'ldd /opt/firefox/firefox-bin 2>&1 | grep "not found" || echo none'
echo "==== try firefox --version ===="
chroot "$CH" bash -c 'export DISPLAY=:99; Xvfb :99 -screen 0 1280x800x24 >/tmp/xvfb.log 2>&1 & XV=$!; sleep 1; /opt/firefox/firefox --version 2>&1 | head -5; kill $XV 2>/dev/null' || true
echo "==== uli health on host python ===="
chroot "$CH" python3 -c "import fastapi, uvicorn; print('ok')"
echo "==== packages gtk ===="
chroot "$CH" dpkg -l libgtk-3-0 libdbus-glib-1-2 libxt6 libx11-xcb1 libasound2 2>/dev/null | grep ^ii || true
