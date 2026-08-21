#!/usr/bin/env bash
# Install real Mozilla Firefox (tarball) into the live chroot — Ubuntu's
# firefox package is a snap stub and does not work offline in live images.
set -euo pipefail
# Intentionally require the canonical builder to pass its validated chroot;
# never guess a legacy workspace and remove files below it implicitly.
CHROOT="${1:-}"
DEFAULT_VER="153.0"
DEFAULT_SHA256="bfc57e7b6b4e6204b11e7e03c4b93cff708e9fb37f6b9948be243455311d82ee"
VER="${FIREFOX_VERSION:-$DEFAULT_VER}"
URL="https://ftp.mozilla.org/pub/firefox/releases/${VER}/linux-x86_64/en-US/firefox-${VER}.tar.xz"
TMP="/tmp/firefox-${VER}.tar.xz"
EXPECTED_SHA256="${FIREFOX_SHA256:-$DEFAULT_SHA256}"

if [ -z "$CHROOT" ] || [ ! -d "$CHROOT" ] || [ "$CHROOT" = "/" ]; then
  echo "usage: $0 /absolute/path/to/chroot" >&2
  exit 2
fi
CHROOT="$(realpath -e "$CHROOT")"
case "$CHROOT" in
  /var/tmp/uli-iso-*/chroot) ;;
  *) echo "Refusing unsafe chroot path: $CHROOT" >&2; exit 2 ;;
esac

if [ "$VER" != "$DEFAULT_VER" ] && [ -z "${FIREFOX_SHA256:-}" ]; then
  echo "FIREFOX_SHA256 is required when overriding FIREFOX_VERSION" >&2
  exit 2
fi

echo "Downloading Firefox ${VER}..."
if [ ! -f "$TMP" ]; then
  curl -L --fail -o "$TMP" "$URL"
fi
printf '%s  %s\n' "$EXPECTED_SHA256" "$TMP" | sha256sum --check --status || {
  rm -f "$TMP"
  echo "Firefox archive checksum mismatch" >&2
  exit 1
}
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
