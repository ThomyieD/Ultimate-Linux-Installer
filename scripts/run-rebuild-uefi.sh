#!/bin/bash
set -euo pipefail
DIR=/root/Linux-Installer/github/Ultimate-Linux-Installer/scripts
cd "$DIR"
for f in lib-iso-uefi.sh rebuild-iso-boot.sh verify-iso-uefi.sh build-iso-simple.sh; do
  python3 -c "from pathlib import Path; p=Path('$f'); p.write_bytes(p.read_bytes().replace(b'\r\n', b'\n').replace(b'\r', b'\n'))"
  chmod +x "$f"
  file "$f"
done
bash "$DIR/rebuild-iso-boot.sh"
