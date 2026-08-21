from __future__ import annotations

import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

CHECK_URLS = (
    "https://deb.debian.org",
    "https://connectivitycheck.gstatic.com/generate_204",
    "http://detectportal.firefox.com/success.txt",
)


def _run(cmd: list[str], *, timeout: float = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def check_internet(timeout: float = 3.0, url: str | None = None) -> bool:
    """Return True only when HTTP(S) *and DNS* work for installer sources.

    A raw connection to a public IP is not sufficient: provisioning needs to
    resolve official repository hostnames.  Treating that as ``online`` made
    the wizard advance although the subsequent signed-source check had to
    fail with a name-resolution error.
    """
    urls = (url,) if url else CHECK_URLS
    for candidate in urls:
        if not candidate:
            continue
        try:
            req = urllib.request.Request(candidate, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                code = getattr(resp, "status", 200)
                if 200 <= code < 500 or code in {204, 301, 302}:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            continue
    return False


@dataclass(frozen=True)
class WifiNetwork:
    ssid: str
    signal: int = 0
    security: str = ""


@dataclass(frozen=True)
class NetDevice:
    name: str
    type: str
    state: str
    connection: str = ""


def nmcli_available() -> bool:
    return bool(shutil.which("nmcli"))


def list_devices() -> list[NetDevice]:
    if not nmcli_available():
        return []
    try:
        result = _run(
            ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "dev", "status"],
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    devices: list[NetDevice] = []
    for line in result.stdout.splitlines():
        parts = line.split(":")
        if len(parts) < 3:
            continue
        devices.append(
            NetDevice(
                name=parts[0],
                type=parts[1],
                state=parts[2],
                connection=parts[3] if len(parts) > 3 else "",
            )
        )
    return devices


def _sysfs_wifi_ifaces() -> list[str]:
    root = Path("/sys/class/net")
    if not root.is_dir():
        return []
    found: list[str] = []
    for iface in root.iterdir():
        if (iface / "wireless").exists() or (iface / "phy80211").exists():
            found.append(iface.name)
    return found


def ensure_networkmanager() -> None:
    if not nmcli_available():
        return
    try:
        if shutil.which("rfkill"):
            _run(["rfkill", "unblock", "all"], timeout=5)
            _run(["rfkill", "unblock", "wifi"], timeout=5)
            _run(["rfkill", "unblock", "wlan"], timeout=5)
        _run(["nmcli", "networking", "on"], timeout=5)
        _run(["nmcli", "radio", "wifi", "on"], timeout=5)
        # Claim any Wi-Fi NIC that udev left unmanaged
        for name in _sysfs_wifi_ifaces():
            _run(["nmcli", "dev", "set", name, "managed", "yes"], timeout=5)
        for dev in list_devices():
            if dev.type == "wifi" and dev.state == "unmanaged":
                _run(["nmcli", "dev", "set", dev.name, "managed", "yes"], timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return


def has_wifi_radio() -> bool:
    """True when a Wi-Fi adapter exists (even if still unmanaged/disconnected)."""
    ensure_networkmanager()
    if _sysfs_wifi_ifaces():
        return True
    return any(d.type == "wifi" for d in list_devices())


def ethernet_carrier() -> bool | None:
    """True if a wired interface reports connected; False if present but down; None if none."""
    eth = [d for d in list_devices() if d.type == "ethernet"]
    if not eth:
        return None
    if any(d.state == "connected" for d in eth):
        return True
    if any(d.state in {"disconnected", "unavailable", "connecting"} for d in eth):
        return False
    return False


def ensure_ethernet(*, wait_seconds: float = 12.0) -> dict[str, object]:
    """Bring wired interfaces up with DHCP and wait briefly for connectivity."""
    ensure_networkmanager()
    actions: list[str] = []
    already_online = check_internet(timeout=1.5)
    eth_devs = [d for d in list_devices() if d.type == "ethernet"]
    for dev in eth_devs:
        if dev.state == "unmanaged":
            try:
                _run(["nmcli", "dev", "set", dev.name, "managed", "yes"], timeout=5)
                actions.append(f"manage:{dev.name}")
            except (OSError, subprocess.TimeoutExpired):
                pass
        needs_connect = (not already_online) or dev.state != "connected"
        if needs_connect:
            try:
                result = _run(["nmcli", "dev", "connect", dev.name], timeout=45)
                actions.append(
                    f"connect:{dev.name}:{'ok' if result.returncode == 0 else 'fail'}"
                )
                if result.returncode != 0 and shutil.which("dhclient"):
                    _run(["dhclient", "-v", dev.name], timeout=30)
                    actions.append(f"dhclient:{dev.name}")
            except (OSError, subprocess.TimeoutExpired) as exc:
                actions.append(f"connect:{dev.name}:error:{exc}")

    deadline = time.monotonic() + wait_seconds
    online = False
    while time.monotonic() < deadline:
        online = check_internet(timeout=2.0)
        if online:
            break
        time.sleep(0.8)
    return {
        "online": online,
        "ethernet": ethernet_carrier(),
        "has_wifi": has_wifi_radio(),
        "devices": [
            {"name": d.name, "type": d.type, "state": d.state, "connection": d.connection}
            for d in list_devices()
        ],
        "actions": actions,
    }


def prepare_and_check(*, wait_seconds: float = 10.0) -> dict[str, object]:
    """Best-effort bring-up then connectivity check — for VMs (bridged) and bare metal."""
    ensure_networkmanager()
    status = ensure_ethernet(wait_seconds=wait_seconds)
    if not status["online"]:
        time.sleep(1.0)
        status["online"] = check_internet(timeout=3.0)
        status["ethernet"] = ethernet_carrier()
        status["has_wifi"] = has_wifi_radio()
        status["devices"] = [
            {"name": d.name, "type": d.type, "state": d.state, "connection": d.connection}
            for d in list_devices()
        ]
    return status


def list_wifi_networks(*, rescan: bool = True) -> list[WifiNetwork]:
    """Wi-Fi scan via nmcli; empty when unavailable."""
    ensure_networkmanager()
    if not nmcli_available():
        return []
    try:
        if rescan:
            _run(["nmcli", "dev", "wifi", "rescan"], timeout=20)
        result = _run(
            ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list"],
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []

    networks: list[WifiNetwork] = []
    seen: set[str] = set()
    for line in result.stdout.splitlines():
        parts = line.split(":")
        if not parts:
            continue
        ssid = parts[0].replace("\\:", ":").strip()
        if not ssid or ssid in seen:
            continue
        seen.add(ssid)
        signal = 0
        security = ""
        if len(parts) >= 2:
            try:
                signal = int(parts[1])
            except ValueError:
                signal = 0
        if len(parts) >= 3:
            security = parts[2]
        networks.append(WifiNetwork(ssid=ssid, signal=signal, security=security))
    networks.sort(key=lambda n: n.signal, reverse=True)
    return networks


def list_wifi_ssids() -> list[str]:
    return [n.ssid for n in list_wifi_networks(rescan=False)]


def connect_wifi(ssid: str, password: str) -> tuple[bool, str]:
    """Connect to Wi-Fi. Returns (ok, error_message)."""
    if not ssid:
        return False, "empty_ssid"
    if not nmcli_available():
        return False, "nmcli_missing"
    ensure_networkmanager()
    cmd = ["nmcli", "dev", "wifi", "connect", ssid]
    if password:
        cmd.extend(["password", password])
    try:
        result = _run(cmd, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if result.returncode == 0:
        return True, ""
    err = (result.stderr or result.stdout or "connect_failed").strip()
    return False, err
