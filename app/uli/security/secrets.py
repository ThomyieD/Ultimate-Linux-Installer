from __future__ import annotations

import hashlib
import hmac
import secrets
from pathlib import Path


def hash_password(password: str) -> str:
    """Create a SHA-512 crypt hash suitable for preseed/autoinstall/kickstart."""
    try:
        import crypt  # Unix only

        return crypt.crypt(password, crypt.mksalt(crypt.METHOD_SHA512))
    except Exception:
        # Dev fallback on Windows – real installs run on Linux live media
        salt = secrets.token_hex(8)
        digest = hashlib.sha512(f"{salt}{password}".encode()).hexdigest()
        return f"$6${salt}${digest}"


def fingerprint_ssh_key(pub_line: str) -> str:
    parts = pub_line.strip().split()
    if len(parts) < 2:
        return "invalid"
    try:
        import base64

        raw = base64.b64decode(parts[1])
        digest = hashlib.sha256(raw).digest()
        fp = base64.b64encode(digest).decode().rstrip("=")
        return f"{parts[0]} SHA256:{fp}"
    except Exception:
        return parts[0]


def fetch_launchpad_keys(username: str) -> list[str]:
    import json
    import urllib.request

    url = f"https://api.launchpad.net/1.0/~{username}/sshkeys"
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    keys = []
    for entry in data.get("entries", []):
        key = entry.get("keytext") or entry.get("key")
        if key:
            keys.append(key.strip())
    return keys


def fetch_github_keys(username: str) -> list[str]:
    import urllib.request

    url = f"https://github.com/{username}.keys"
    with urllib.request.urlopen(url, timeout=10) as resp:
        text = resp.read().decode()
    return [line.strip() for line in text.splitlines() if line.strip()]


def write_authorized_keys(path: Path, keys: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(keys) + ("\n" if keys else ""), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def verify_sha256(file_path: Path, expected_hex: str) -> bool:
    h = hashlib.sha256()
    with file_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return hmac.compare_digest(h.hexdigest().lower(), expected_hex.lower())
