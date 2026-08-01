from __future__ import annotations

import socket
import urllib.request


def check_internet(timeout: float = 3.0, url: str = "https://deb.debian.org") -> bool:
    """Return True when outbound HTTPS works."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= getattr(resp, "status", 200) < 500
    except Exception:
        # Fallback: DNS + TCP to well-known resolver
        try:
            socket.create_connection(("1.1.1.1", 443), timeout=timeout).close()
            return True
        except OSError:
            return False


def list_wifi_ssids() -> list[str]:
    """Best-effort Wi-Fi scan via nmcli; empty when unavailable."""
    import shutil
    import subprocess

    if not shutil.which("nmcli"):
        return []
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "SSID", "dev", "wifi", "list"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        ssids = []
        for line in result.stdout.splitlines():
            name = line.strip()
            if name and name not in ssids:
                ssids.append(name)
        return ssids
    except (OSError, subprocess.TimeoutExpired):
        return []


def connect_wifi(ssid: str, password: str) -> bool:
    import shutil
    import subprocess

    if not shutil.which("nmcli"):
        return False
    result = subprocess.run(
        ["nmcli", "dev", "wifi", "connect", ssid, "password", password],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0
