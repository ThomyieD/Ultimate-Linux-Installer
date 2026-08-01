#!/usr/bin/env bash
# Minimal 1x1 PNG placeholders are generated at build time if missing.
# This script creates a dark solid background and selection bar for GRUB themes.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

make_png() {
  local out="$1" w="$2" h="$3" rgb="$4"
  python3 - <<PY
from pathlib import Path
# Write a tiny uncompressed PPM then convert if pillow exists; else raw PPM rename notice
w, h = $w, $h
r, g, b = map(int, "$rgb".split(","))
path = Path(r"$out")
path.parent.mkdir(parents=True, exist_ok=True)
try:
    from PIL import Image
    img = Image.new("RGB", (w, h), (r, g, b))
    img.save(path)
except Exception:
    # Fallback: write PPM (GRUB needs PNG – build host should have pillow)
    ppm = path.with_suffix(".ppm")
    ppm.write_bytes(("P6\n%d %d\n255\n" % (w, h)).encode() + bytes([r, g, b]) * (w * h))
    print(f"Wrote {ppm}; install pillow to generate PNG: {path}")
PY
}

for theme in uli-lenovo uli-dark; do
  dir="$ROOT/themes/grub/$theme"
  make_png "$dir/background.png" 1920 1080 "18,20,23"
  make_png "$dir/select_c.png" 600 42 "60,60,65"
  make_png "$dir/select_w.png" 8 42 "60,60,65"
  make_png "$dir/select_e.png" 8 42 "60,60,65"
done

echo "Theme assets ready."
