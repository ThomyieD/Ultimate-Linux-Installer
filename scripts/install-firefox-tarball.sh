#!/bin/bash
# Install real Mozilla Firefox (tarball) into the live chroot — Ubuntu's
# firefox package is a snap stub and does not work offline in live images.
set -euo pipefail
CHROOT="${1:-/var/tmp/uli-iso/chroot}"
VER="${FIREFOX_VERSION:-140.0.4}"
URL="https://ftp.mozilla.org/pub/firefox/releases/${VER}/linux-x86_64/en-US/firefox-${VER}.tar.xz"
TMP="/tmp/firefox-${VER}.tar.xz"

echo "Downloading Firefox ${VER}..."
if [ ! -f "$TMP" ]; then
  curl -L --fail -o "$TMP" "$URL"
fi
rm -rf "$CHROOT/opt/firefox"
mkdir -p "$CHROOT/opt"
tar -xJf "$TMP" -C "$CHROOT/opt"
ln -sfn /opt/firefox/firefox "$CHROOT/usr/local/bin/firefox"
# Wrapper preferred by uli-start
cat >"$CHROOT/usr/local/bin/uli-firefox" <<'EOF'
#!/bin/sh
exec /opt/firefox/firefox "$@"
EOF
chmod +x "$CHROOT/usr/local/bin/uli-firefox"
# Prefer our binary over snap stub
ln -sfn /opt/firefox/firefox "$CHROOT/usr/bin/firefox-mozilla"
# Make PATH prefer local
if [ -x "$CHROOT/usr/bin/firefox" ] && head -c 80 "$CHROOT/usr/bin/firefox" | grep -q snap; then
  mv "$CHROOT/usr/bin/firefox" "$CHROOT/usr/bin/firefox.snap-stub"
  printf '#!/bin/sh\nexec /opt/firefox/firefox "$@"\n' >"$CHROOT/usr/bin/firefox"
  chmod +x "$CHROOT/usr/bin/firefox"
fi
ls -lh "$CHROOT/opt/firefox/firefox"
echo "Firefox installed into chroot"
