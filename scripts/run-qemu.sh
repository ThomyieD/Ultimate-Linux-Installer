#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ISO="${1:-$ROOT/artifacts/ultimate-linux-installer.iso}"
DISK="${2:-$ROOT/artifacts/testdisk.qcow2}"
mkdir -p "$ROOT/artifacts"
[[ -f "$DISK" ]] || qemu-img create -f qcow2 "$DISK" 120G

OVMF_CODE="${OVMF_CODE:-/usr/share/OVMF/OVMF_CODE.fd}"
OVMF_VARS_TEMPLATE="${OVMF_VARS_TEMPLATE:-/usr/share/OVMF/OVMF_VARS.fd}"
VARS="$ROOT/artifacts/OVMF_VARS.fd"
[[ -f "$VARS" ]] || cp "$OVMF_VARS_TEMPLATE" "$VARS"

qemu-system-x86_64 \
  -enable-kvm \
  -machine q35 \
  -cpu host \
  -m 8192 \
  -smp 4 \
  -drive if=pflash,format=raw,readonly=on,file="$OVMF_CODE" \
  -drive if=pflash,format=raw,file="$VARS" \
  -drive file="$DISK",format=qcow2,if=virtio \
  -cdrom "$ISO" \
  -boot order=d \
  -netdev user,id=net0 \
  -device virtio-net-pci,netdev=net0 \
  -vga virtio
