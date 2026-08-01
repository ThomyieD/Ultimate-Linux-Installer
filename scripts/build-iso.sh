#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/live-build"

if ! command -v lb >/dev/null; then
  echo "live-build (lb) is required on the Linux build host." >&2
  exit 1
fi

chmod +x config/hooks/normal/*.hook.chroot 2>/dev/null || true

# Wipe auto-generated lb config leftovers (keep our tracked overlays only)
mkdir -p config/package-lists config/hooks/normal config/includes.chroot
find config -mindepth 1 -maxdepth 1 \
  ! -name 'package-lists' \
  ! -name 'hooks' \
  ! -name 'includes.chroot' \
  -exec rm -rf {} +

# Never rsync live-build into itself (causes recursive nesting + disk fill)
rm -rf config/includes.chroot/opt/uli
mkdir -p config/includes.chroot/opt/uli/src
rsync -a \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '_doc_extract' \
  --exclude '__pycache__' \
  --exclude '*.qcow2' \
  --exclude '*.iso' \
  --exclude 'artifacts' \
  --exclude 'live-build' \
  --exclude 'docs/reference' \
  "$ROOT/" config/includes.chroot/opt/uli/src/

lb clean --purge || lb clean || true

UBU="http://archive.ubuntu.com/ubuntu/"
# Compatible with Ubuntu's live-build 3.0~a57 (Ubuntu live image)
lb config \
  --ignore-system-defaults \
  --mode ubuntu \
  --architectures amd64 \
  --binary-images iso-hybrid \
  --bootloader grub \
  --bootappend-live "boot=live components quiet splash hostname=uli-live username=uli locales=de_DE.UTF-8 keyboard-layouts=de timezone=Europe/Berlin" \
  --debian-installer false \
  --distribution jammy \
  --parent-distribution jammy \
  --archive-areas "main restricted universe multiverse" \
  --parent-archive-areas "main restricted universe multiverse" \
  --mirror-bootstrap "$UBU" \
  --mirror-chroot "$UBU" \
  --mirror-binary "$UBU" \
  --mirror-chroot-security "$UBU" \
  --mirror-binary-security "$UBU" \
  --mirror-chroot-volatile "$UBU" \
  --mirror-binary-volatile "$UBU" \
  --parent-mirror-bootstrap "$UBU" \
  --parent-mirror-chroot "$UBU" \
  --parent-mirror-binary "$UBU" \
  --parent-mirror-chroot-security "$UBU" \
  --parent-mirror-binary-security "$UBU" \
  --parent-mirror-chroot-volatile "$UBU" \
  --parent-mirror-binary-volatile "$UBU" \
  --apt-indices false \
  --apt-recommends false \
  --firmware-chroot true \
  --security false \
  --iso-application "Ultimate Linux Installer" \
  --iso-preparer "ULI" \
  --iso-publisher "Ultimate Linux Installer" \
  --iso-volume "ULI_0_1_0"



echo "Starting lb build (this can take a long time)..."
lb build

mkdir -p "$ROOT/artifacts"
ISO_SRC=""
for candidate in \
  live-image-amd64.hybrid.iso \
  live-image-amd64.iso \
  binary.hybrid.iso \
  binary.iso
do
  if [[ -f "$candidate" ]]; then
    ISO_SRC="$candidate"
    break
  fi
done

if [[ -z "$ISO_SRC" ]]; then
  echo "ISO not found after lb build. Directory listing:" >&2
  ls -lah >&2 || true
  exit 1
fi

OUT="$ROOT/artifacts/ultimate-linux-installer-0.1.0-amd64.iso"
cp -v "$ISO_SRC" "$OUT"
ln -sfn "$(basename "$OUT")" "$ROOT/artifacts/ultimate-linux-installer.iso"
ls -lh "$OUT"
echo "ISO: $OUT"
