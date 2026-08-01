#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/live-build"

if ! command -v lb >/dev/null; then
  echo "live-build (lb) is required on the Linux build host." >&2
  exit 1
fi

chmod +x config/hooks/normal/*.hook.chroot 2>/dev/null || true

# Seed application into chroot include path
mkdir -p config/includes.chroot/opt/uli
rsync -a --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '_doc_extract' \
  --exclude '__pycache__' \
  --exclude '*.qcow2' \
  --exclude '*.iso' \
  --exclude 'artifacts' \
  --exclude 'docs/reference' \
  "$ROOT/" config/includes.chroot/opt/uli/src/

# Avoid carrying a nested live-build tree into the image
rm -rf config/includes.chroot/opt/uli/src/live-build \
       config/includes.chroot/opt/uli/src/artifacts \
       config/includes.chroot/opt/uli/src/.venv || true

lb clean --purge || lb clean || true

# Ubuntu hosts often need explicit debian mode + mirror
lb config \
  --mode debian \
  --architectures amd64 \
  --binary-images iso-hybrid \
  --bootloaders "grub-efi,syslinux" \
  --bootappend-live "boot=live components quiet splash hostname=uli-live username=uli locales=de_DE.UTF-8 keyboard-layouts=de timezone=Europe/Berlin" \
  --debian-installer none \
  --distribution bookworm \
  --parent-distribution bookworm \
  --archive-areas "main contrib non-free non-free-firmware" \
  --parent-archive-areas "main contrib non-free non-free-firmware" \
  --mirror-bootstrap "https://deb.debian.org/debian/" \
  --mirror-chroot "https://deb.debian.org/debian/" \
  --mirror-binary "https://deb.debian.org/debian/" \
  --mirror-chroot-security "https://security.debian.org/debian-security/" \
  --mirror-binary-security "https://security.debian.org/debian-security/" \
  --apt-indices false \
  --apt-recommends false \
  --firmware-chroot true \
  --uefi-secure-boot disable \
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
