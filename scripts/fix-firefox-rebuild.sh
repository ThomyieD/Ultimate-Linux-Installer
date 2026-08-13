#!/bin/bash
set -euo pipefail
CH=/var/tmp/uli-iso/chroot
ROOT=/root/Linux-Installer/github/Ultimate-Linux-Installer

cat >"$CH/usr/bin/firefox" <<'EOF'
#!/bin/sh
exec /opt/firefox/firefox "$@"
EOF
cat >"$CH/usr/local/bin/uli-firefox" <<'EOF'
#!/bin/sh
exec /opt/firefox/firefox "$@"
EOF
chmod +x "$CH/usr/bin/firefox" "$CH/usr/local/bin/uli-firefox"

cat >"$CH/usr/local/bin/uli-start" <<'EOF'
#!/bin/sh
export PYTHONPATH=/usr/local/lib/python3.10/dist-packages
export ULI_SIMULATE_DISK=0
export ULI_DRY_RUN=0
mkdir -p /var/log/uli
exec >>/var/log/uli/uli-start.log 2>&1
echo "==== $(date -Is) DISPLAY=$DISPLAY ===="

uli --ui web --host 127.0.0.1 --port 8787 &
WEB_PID=$!
i=0
while [ "$i" -lt 60 ]; do
  if curl -sf http://127.0.0.1:8787/api/health >/dev/null 2>&1; then
    break
  fi
  i=$((i + 1))
  sleep 0.5
done

if [ -x /opt/firefox/firefox ]; then
  exec /opt/firefox/firefox --kiosk --new-instance "http://127.0.0.1:8787/"
fi
echo "No browser found — web UI on :8787 (pid $WEB_PID)"
xterm -hold -e "echo ULI web UI: http://127.0.0.1:8787; tail -f /var/log/uli/uli-start.log" &
wait "$WEB_PID"
EOF
chmod +x "$CH/usr/local/bin/uli-start"

echo "wrappers:"
head -3 "$CH/usr/bin/firefox"
head -3 "$CH/usr/local/bin/uli-start"

# shellcheck source=lib-iso-uefi.sh
source "$ROOT/scripts/lib-iso-uefi.sh"
WORK=/var/tmp/uli-iso
IMG=$WORK/image
OUT_ISO=$ROOT/artifacts/ultimate-linux-installer-0.2.0-amd64.iso
LABEL=ULI_0_2_0
rm -f "$IMG/live/filesystem.squashfs" "$OUT_ISO"
mksquashfs "$CH" "$IMG/live/filesystem.squashfs" -comp xz -e boot
mkdir -p "$IMG/boot/grub" "$WORK/scratch"
cat >"$IMG/boot/grub/grub.cfg" <<'GCFG'
set timeout=3
set default=0
insmod all_video
insmod linux
insmod linuxefi
serial --unit=0 --speed=115200
terminal_input serial console
terminal_output serial console
menuentry "Ultimate Linux Installer" {
    echo "Booting Ultimate Linux Installer..."
    linux /live/vmlinuz boot=live components quiet splash hostname=uli-live username=uli console=tty0 console=ttyS0,115200n8
    initrd /live/initrd.img
}
GCFG
GRUB_EFI_DIR="$(uli_find_grub_efi_dir "$CH")"
BOOT_IMG=$WORK/scratch/efi.img
uli_make_efi_boot_image "$BOOT_IMG" "$IMG" "$LABEL" "$GRUB_EFI_DIR"
cp "$BOOT_IMG" "$IMG/EFI/BOOT/efiboot.img"
uli_xorriso_hybrid "$OUT_ISO" "$LABEL" "$IMG"
ln -sfn "$(basename "$OUT_ISO")" "$ROOT/artifacts/ultimate-linux-installer.iso"
ls -lh "$OUT_ISO"
echo DONE
