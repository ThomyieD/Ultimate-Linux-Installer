#!/usr/bin/env bash
# Generate deterministic PNG assets without third-party Python modules.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

make_png() {
  local out="$1" width="$2" height="$3" rgb="$4" shape="${5:-solid}"
  python3 - "$out" "$width" "$height" "$rgb" "$shape" <<'PY'
import binascii
import math
import struct
import sys
import zlib
from pathlib import Path

path = Path(sys.argv[1])
width, height = int(sys.argv[2]), int(sys.argv[3])
red, green, blue = (int(part) for part in sys.argv[4].split(","))
shape = sys.argv[5]
path.parent.mkdir(parents=True, exist_ok=True)

rows = []
cx, cy = (width - 1) / 2, (height - 1) / 2
radius = min(width, height) * 0.43
for y in range(height):
    row = bytearray([0])
    for x in range(width):
        if shape == "icon":
            distance = math.hypot(x - cx, y - cy)
            if distance <= radius:
                if distance < radius * 0.28:
                    pixel = (244, 241, 234, 255)
                else:
                    pixel = (red, green, blue, 255)
            else:
                pixel = (0, 0, 0, 0)
        else:
            pixel = (red, green, blue, 255)
        row.extend(pixel)
    rows.append(bytes(row))

def chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)
    )

raw = b"".join(rows)
png = (
    b"\x89PNG\r\n\x1a\n"
    + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    + chunk(b"IDAT", zlib.compress(raw, 9))
    + chunk(b"IEND", b"")
)
path.write_bytes(png)
PY
}

make_terminal_box() {
  local dir="$1" center_rgb="$2" border_rgb="$3"

  # GRUB's pixmap-style is a conventional nine-slice: a scalable centre,
  # four 2 px edges and four square corners.  Keeping the slices tiny avoids
  # wasting space on the ESP while still producing a crisp terminal frame.
  make_png "$dir/terminal_box_c.png" 32 32 "$center_rgb"
  make_png "$dir/terminal_box_n.png" 32 2 "$border_rgb"
  make_png "$dir/terminal_box_s.png" 32 2 "$border_rgb"
  make_png "$dir/terminal_box_w.png" 2 32 "$border_rgb"
  make_png "$dir/terminal_box_e.png" 2 32 "$border_rgb"
  make_png "$dir/terminal_box_nw.png" 2 2 "$border_rgb"
  make_png "$dir/terminal_box_ne.png" 2 2 "$border_rgb"
  make_png "$dir/terminal_box_sw.png" 2 2 "$border_rgb"
  make_png "$dir/terminal_box_se.png" 2 2 "$border_rgb"
}

verify_theme_assets() {
  local dir="$1" asset slice
  local -a required=(
    background.png select_c.png select_w.png select_e.png
    icons/debian.png icons/ubuntu.png icons/fedora.png icons/arch.png
    icons/kali.png icons/linuxmint.png icons/gnu-linux.png icons/os.png
  )

  for asset in "${required[@]}"; do
    [ -s "$dir/$asset" ] || {
      echo "Missing generated theme asset: $dir/$asset" >&2
      return 1
    }
  done

  if grep -Eq '^[[:space:]]*terminal-box:' "$dir/theme.txt"; then
    for slice in c n s w e nw ne sw se; do
      [ -s "$dir/terminal_box_${slice}.png" ] || {
        echo "Missing terminal nine-slice asset: $dir/terminal_box_${slice}.png" >&2
        return 1
      }
    done
  fi
}

for theme in uli-lenovo uli-dark; do
  dir="$ROOT/themes/grub/$theme"
  make_png "$dir/background.png" 1920 1080 "18,20,23"
  make_png "$dir/select_c.png" 600 42 "60,60,65"
  make_png "$dir/select_w.png" 8 42 "60,60,65"
  make_png "$dir/select_e.png" 8 42 "60,60,65"

  make_png "$dir/icons/debian.png" 32 32 "215,10,83" icon
  make_png "$dir/icons/ubuntu.png" 32 32 "233,84,32" icon
  make_png "$dir/icons/fedora.png" 32 32 "81,135,214" icon
  make_png "$dir/icons/arch.png" 32 32 "23,147,209" icon
  make_png "$dir/icons/kali.png" 32 32 "75,141,207" icon
  make_png "$dir/icons/linuxmint.png" 32 32 "104,184,72" icon
  make_png "$dir/icons/gnu-linux.png" 32 32 "170,170,170" icon
  make_png "$dir/icons/os.png" 32 32 "170,170,170" icon

  if grep -Eq '^[[:space:]]*terminal-box:' "$dir/theme.txt"; then
    make_terminal_box "$dir" "10,12,16" "82,90,100"
  fi
  verify_theme_assets "$dir"
done

echo "Theme assets ready."
