#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/live-build"

if ! command -v lb >/dev/null; then
  echo "live-build (lb) is required on the Linux build host." >&2
  exit 1
fi

# Seed application into chroot include path
mkdir -p config/includes.chroot/opt/uli
rsync -a --delete \
  --exclude '.git' \
  --exclude '_doc_extract' \
  --exclude '*.qcow2' \
  --exclude '*.iso' \
  "$ROOT/" config/includes.chroot/opt/uli/src/

lb clean
lb config \
  --architectures amd64 \
  --binary-images iso-hybrid \
  --bootappend-live "boot=live components quiet splash username=uli" \
  --debian-installer none \
  --distribution bookworm \
  --archive-areas "main contrib non-free non-free-firmware" \
  --uefi-secure-boot disable \
  --iso-application "Ultimate Linux Installer" \
  --iso-volume "ULI"

lb build
mkdir -p "$ROOT/artifacts"
cp -v live-image-amd64.hybrid.iso "$ROOT/artifacts/ultimate-linux-installer.iso"
echo "ISO: $ROOT/artifacts/ultimate-linux-installer.iso"
