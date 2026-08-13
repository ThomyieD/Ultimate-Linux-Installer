#!/bin/bash
# Wait until uli.main is running (via serial), then screendump.
set -euo pipefail
ISO="${1:?iso}"
OUT_DIR="${2:-$(dirname "$ISO")}"
mkdir -p "$OUT_DIR"
OVMF_CODE=/usr/share/OVMF/OVMF_CODE_4M.fd
OVMF_VARS_SRC=/usr/share/OVMF/OVMF_VARS_4M.fd
TMP=$(mktemp -d /tmp/uli-guiv2-XXXXXX)
cp "$OVMF_VARS_SRC" "$TMP/vars.fd"
PORT=4466
MON="$TMP/monitor.sock"
PPM="$OUT_DIR/uli-gui-screendump.ppm"
PNG="$OUT_DIR/uli-gui-screendump.png"
export ULI_V_PORT="$PORT" ULI_V_MON="$MON" ULI_V_PPM="$PPM" ULI_V_PNG="$PNG" ULI_V_OUT="$OUT_DIR/uli-gui-verify.txt"

qemu-system-x86_64 \
  -machine q35,accel=tcg -cpu max -m 3072 -smp 2 \
  -drive if=pflash,format=raw,readonly=on,file="$OVMF_CODE" \
  -drive if=pflash,format=raw,file="$TMP/vars.fd" \
  -cdrom "$ISO" -boot order=d -vga std -display none \
  -serial telnet:127.0.0.1:${PORT},server,nowait \
  -monitor unix:"$MON",server,nowait \
  >/tmp/uli-guiv2.out 2>/tmp/uli-guiv2.err &
QPID=$!
cleanup() { kill "$QPID" 2>/dev/null || true; wait "$QPID" 2>/dev/null || true; rm -rf "$TMP"; }
trap cleanup EXIT

python3 - <<'PY'
import os, socket, time, sys, re
port = int(os.environ["ULI_V_PORT"])
mon = os.environ["ULI_V_MON"]
ppm = os.environ["ULI_V_PPM"]
png = os.environ["ULI_V_PNG"]
out_txt = os.environ["ULI_V_OUT"]

def connect_serial():
    for _ in range(90):
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=2)
        except OSError:
            time.sleep(1)
    raise SystemExit("serial connect failed")

s = connect_serial()
s.settimeout(1.0)
buf = bytearray()

def read_more(secs=1.0):
    end = time.time() + secs
    while time.time() < end:
        try:
            chunk = s.recv(4096)
            if chunk:
                buf.extend(chunk)
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
        except socket.timeout:
            pass

def wait_for(pat, timeout=400):
    rx = re.compile(pat)
    end = time.time() + timeout
    while time.time() < end:
        read_more(1)
        if rx.search(buf.decode("utf-8", "replace")):
            return True
    return False

def send(line):
    s.sendall((line + "\r\n").encode())

print("waiting login", flush=True)
assert wait_for(r"login:", 420), "no login"
send("uli")
assert wait_for(r"[Pp]assword:", 30)
send("uli")
time.sleep(2)
read_more(2)

found = False
for n in range(60):
    send("pgrep -af uli.main || true; echo CHECK_%d" % n)
    if wait_for(r"CHECK_%d" % n, 15):
        text = buf.decode("utf-8", "replace")
        tail = text.split("CHECK_%d" % n)[0][-800:]
        if "uli.main" in tail:
            print("uli.main is running", flush=True)
            found = True
            break
    time.sleep(2)
if not found:
    raise SystemExit("uli.main never appeared")

# Switch VGA to the X VT so screendump sees the GUI, not getty on tty1
send("echo uli | sudo -S chvt 7 >/dev/null 2>&1; echo CHVT_DONE")
wait_for(r"CHVT_DONE", 30)
time.sleep(20)

ms = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
ms.connect(mon)
ms.sendall(("screendump %s\n" % ppm).encode())
time.sleep(1.2)
ms.sendall(b"quit\n")
time.sleep(1)

from PIL import Image
im = Image.open(ppm)
im.save(png)
w, h = im.size
px = im.load()
bright = near_white = 0
for y in range(0, h, 8):
    for x in range(0, w, 8):
        r, g, b = px[x, y][:3]
        if max(r, g, b) > 30:
            bright += 1
        if r > 200 and g > 200 and b > 200:
            near_white += 1
print("size=%dx%d bright=%d near_white=%d" % (w, h, bright, near_white))
if near_white > 500:
    raise SystemExit("FAIL still console-like")
if bright < 80:
    raise SystemExit("FAIL nearly black")
print("PASS GUI screendump looks like painted UI")
open(out_txt, "w", encoding="utf-8").write(
    "PASS bright=%d near_white=%d\n" % (bright, near_white)
)
PY
ls -lh "$PNG"
echo DONE
