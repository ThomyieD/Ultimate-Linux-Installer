#!/bin/bash
set -euo pipefail
WORK=/var/tmp/uli-iso
CHROOT=$WORK/chroot
IMG=$WORK/image
ROOT=/root/Linux-Installer/github/Ultimate-Linux-Installer
OUT_DIR=$ROOT/artifacts
OUT_ISO=$OUT_DIR/ultimate-linux-installer-0.1.0-amd64.iso
LABEL=ULI_0_1_0

mount --bind /dev "$CHROOT/dev" 2>/dev/null || true
mount --bind /dev/pts "$CHROOT/dev/pts" 2>/dev/null || true
mount -t proc proc "$CHROOT/proc" 2>/dev/null || true
mount -t sysfs sysfs "$CHROOT/sys" 2>/dev/null || true
cleanup() {
  umount -lf "$CHROOT/dev/pts" 2>/dev/null || true
  umount -lf "$CHROOT/dev" 2>/dev/null || true
  umount -lf "$CHROOT/proc" 2>/dev/null || true
  umount -lf "$CHROOT/sys" 2>/dev/null || true
}
trap cleanup EXIT

# Ensure app is importable
mkdir -p "$CHROOT/opt/uli/src"
rsync -a --exclude '.git' --exclude '.venv' --exclude 'live-build' --exclude 'artifacts' --exclude 'docs/reference' --exclude '__pycache__' "$ROOT/" "$CHROOT/opt/uli/src/"
mkdir -p "$CHROOT/usr/local/lib/python3.10/dist-packages"
# Link/copy package onto path
rm -rf "$CHROOT/usr/local/lib/python3.10/dist-packages/uli"
cp -a "$CHROOT/opt/uli/src/app/uli" "$CHROOT/usr/local/lib/python3.10/dist-packages/uli"
printf '#!/bin/sh\nexport PYTHONPATH=/usr/local/lib/python3.10/dist-packages\nexec python3 -m uli.main "$@"\n' >"$CHROOT/usr/local/bin/uli"
chmod +x "$CHROOT/usr/local/bin/uli"
cat >"$CHROOT/usr/local/bin/uli-start" <<'EOF'
#!/bin/sh
export PYTHONPATH=/usr/local/lib/python3.10/dist-packages
export ULI_SIMULATE_DISK=0
export ULI_DRY_RUN=0
export QT_QPA_PLATFORM=xcb
sleep 1
exec uli --lang de
EOF
chmod +x "$CHROOT/usr/local/bin/uli-start"

# User setup (tolerant)
chroot "$CHROOT" groupadd -f netdev || true
chroot "$CHROOT" groupadd -f sudo || true
chroot "$CHROOT" useradd -m -G sudo,audio,video,netdev -s /bin/bash uli 2>/dev/null || true
chroot "$CHROOT" bash -c 'echo uli:uli | chpasswd' 2>/dev/null || true
chroot "$CHROOT" systemctl enable NetworkManager.service 2>/dev/null || true
chroot "$CHROOT" systemctl enable lightdm.service 2>/dev/null || true

mkdir -p "$CHROOT/etc/xdg/autostart" "$CHROOT/etc/xdg/openbox" "$CHROOT/etc/lightdm"
cat >"$CHROOT/etc/xdg/autostart/uli.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Ultimate Linux Installer
Exec=/usr/local/bin/uli-start
X-GNOME-Autostart-enabled=true
EOF
cat >"$CHROOT/etc/xdg/openbox/autostart" <<'EOF'
#!/bin/sh
/usr/local/bin/uli-start &
EOF
chmod +x "$CHROOT/etc/xdg/openbox/autostart"
cat >"$CHROOT/etc/lightdm/lightdm.conf" <<'EOF'
[Seat:*]
autologin-user=uli
autologin-user-timeout=0
user-session=openbox
greeter-session=lightdm-gtk-greeter
EOF

chroot "$CHROOT" apt-get clean || true
rm -rf "$CHROOT/var/lib/apt/lists"/* "$CHROOT/tmp"/* "$CHROOT/var/tmp"/* || true
cleanup
trap - EXIT

echo "[squashfs]"
mkdir -p "$IMG/live" "$IMG/boot/grub" "$IMG/EFI/BOOT" "$IMG/isolinux"
rm -f "$IMG/live/filesystem.squashfs"
mksquashfs "$CHROOT" "$IMG/live/filesystem.squashfs" -comp xz -e boot
KVER=$(ls "$CHROOT"/boot/vmlinuz-* | sed 's|.*/vmlinuz-||' | sort -V | tail -n1)
cp "$CHROOT/boot/vmlinuz-$KVER" "$IMG/live/vmlinuz"
cp "$CHROOT/boot/initrd.img-$KVER" "$IMG/live/initrd.img"

echo "[bootloaders]"
cp /usr/lib/ISOLINUX/isolinux.bin "$IMG/isolinux/" 2>/dev/null || cp "$CHROOT/usr/lib/ISOLINUX/isolinux.bin" "$IMG/isolinux/"
cp /usr/lib/syslinux/modules/bios/*.c32 "$IMG/isolinux/" 2>/dev/null || cp "$CHROOT/usr/lib/syslinux/modules/bios/"*.c32 "$IMG/isolinux/" 2>/dev/null || true
cat >"$IMG/isolinux/isolinux.cfg" <<'EOF'
UI menu.c32
PROMPT 0
TIMEOUT 30
DEFAULT uli
LABEL uli
  MENU LABEL Ultimate Linux Installer
  KERNEL /live/vmlinuz
  APPEND initrd=/live/initrd.img boot=live components quiet splash hostname=uli-live username=uli
EOF
cat >"$IMG/boot/grub/grub.cfg" <<'EOF'
set timeout=5
set default=0
menuentry "Ultimate Linux Installer" {
    linux /live/vmlinuz boot=live components quiet splash hostname=uli-live username=uli
    initrd /live/initrd.img
}
EOF

BOOT_IMG=$WORK/scratch/efi.img
mkdir -p "$WORK/scratch"
rm -f "$BOOT_IMG"
dd if=/dev/zero of="$BOOT_IMG" bs=1M count=16 status=none
mkfs.vfat "$BOOT_IMG" >/dev/null
mkdir -p "$WORK/scratch/efimount"
mount "$BOOT_IMG" "$WORK/scratch/efimount"
mkdir -p "$WORK/scratch/efimount/EFI/BOOT"
if [ -f "$CHROOT/usr/lib/shim/shimx64.efi.signed" ]; then
  cp "$CHROOT/usr/lib/shim/shimx64.efi.signed" "$WORK/scratch/efimount/EFI/BOOT/BOOTX64.EFI"
elif [ -f /usr/lib/shim/shimx64.efi.signed ]; then
  cp /usr/lib/shim/shimx64.efi.signed "$WORK/scratch/efimount/EFI/BOOT/BOOTX64.EFI"
else
  grub-mkimage -O x86_64-efi -o "$WORK/scratch/efimount/EFI/BOOT/BOOTX64.EFI" -p /boot/grub iso9660 fat part_gpt part_msdos normal linux configfile search search_label echo ls || true
fi
cp "$IMG/boot/grub/grub.cfg" "$WORK/scratch/efimount/boot/grub/grub.cfg" 2>/dev/null || \
  (mkdir -p "$WORK/scratch/efimount/boot/grub" && cp "$IMG/boot/grub/grub.cfg" "$WORK/scratch/efimount/boot/grub/grub.cfg")
umount "$WORK/scratch/efimount"
cp "$BOOT_IMG" "$IMG/EFI/BOOT/efiboot.img"

echo "[xorriso]"
mkdir -p "$OUT_DIR"
# free some space first
rm -rf "$CHROOT/usr/share/doc" "$CHROOT/usr/share/man" 2>/dev/null || true
xorriso -as mkisofs \
  -iso-level 3 \
  -full-iso9660-filenames \
  -volid "$LABEL" \
  -eltorito-boot isolinux/isolinux.bin \
  -eltorito-catalog isolinux/boot.cat \
  -no-emul-boot -boot-load-size 4 -boot-info-table \
  -eltorito-alt-boot \
  -e EFI/BOOT/efiboot.img \
  -no-emul-boot \
  -isohybrid-gpt-basdat \
  -output "$OUT_ISO" \
  "$IMG"

ln -sfn "$(basename "$OUT_ISO")" "$OUT_DIR/ultimate-linux-installer.iso"
ls -lh "$OUT_ISO"
echo "ISO_READY=$OUT_ISO"