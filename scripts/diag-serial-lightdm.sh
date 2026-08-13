#!/bin/bash
set -euo pipefail
ISO="${1:?iso}"
OUT="${2:-/tmp/uli-serial-diag.txt}"
OVMF_CODE=/usr/share/OVMF/OVMF_CODE_4M.fd
OVMF_VARS_SRC=/usr/share/OVMF/OVMF_VARS_4M.fd
TMP=$(mktemp -d /tmp/uli-sdiag-XXXXXX)
cp "$OVMF_VARS_SRC" "$TMP/vars.fd"
PORT=4455

qemu-system-x86_64 \
  -machine q35,accel=tcg -cpu max -m 3072 -smp 2 \
  -drive if=pflash,format=raw,readonly=on,file="$OVMF_CODE" \
  -drive if=pflash,format=raw,file="$TMP/vars.fd" \
  -cdrom "$ISO" -boot order=d -vga std -display none \
  -serial telnet:127.0.0.1:${PORT},server,nowait \
  >/tmp/uli-sdiag-qemu.out 2>/tmp/uli-sdiag-qemu.err &
QPID=$!
cleanup() { kill $QPID 2>/dev/null || true; wait $QPID 2>/dev/null || true; rm -rf "$TMP"; }
trap cleanup EXIT

python3 - <<PY
import socket, time, sys, re
port = $PORT
out_path = "$OUT"
# connect
s = None
for i in range(60):
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=2)
        break
    except OSError:
        time.sleep(1)
else:
    raise SystemExit("telnet serial connect failed")
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
            else:
                time.sleep(0.05)
        except socket.timeout:
            pass

def wait_for(pattern, timeout=300):
    end = time.time() + timeout
    rx = re.compile(pattern)
    while time.time() < end:
        read_more(1.0)
        if rx.search(buf.decode("utf-8", "replace")):
            return True
    return False

def send(line):
    s.sendall((line + "\r\n").encode())

print("waiting for login...", flush=True)
if not wait_for(r"login:", 420):
    open(out_path, "wb").write(buf)
    raise SystemExit("no login")
send("uli")
wait_for(r"[Pp]assword:", 30)
send("uli")
time.sleep(2)
read_more(2)
cmds = [
    "id; whoami",
    "systemctl is-system-running || true",
    "systemctl get-default || true",
    "systemctl status lightdm --no-pager -l || true",
    "journalctl -u lightdm -b --no-pager -n 100 || true",
    "ls -la /var/log/lightdm 2>/dev/null || true",
    "tail -n 100 /var/log/lightdm/lightdm.log 2>/dev/null || true",
    "tail -n 60 /var/log/Xorg.0.log 2>/dev/null || true",
    "tail -n 80 /var/log/uli/uli-start.log 2>/dev/null || true",
    "ps -ef | grep -E 'lightdm|Xorg|openbox|uli|python' | grep -v grep || true",
    "echo DIAG_DONE",
]
for c in cmds:
    send(c)
    read_more(2.5)
wait_for(r"DIAG_DONE", 90)
read_more(2)
open(out_path, "wb").write(buf)
print("\\nWrote", out_path, "len", len(buf), flush=True)
PY
