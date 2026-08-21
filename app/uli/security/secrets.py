from __future__ import annotations

import binascii
import hashlib
import hmac
import re
import secrets
import subprocess
from pathlib import Path

_SSH_KEY_RE = re.compile(
    r"^(?:ssh-(?:ed25519|rsa)|ecdsa-sha2-nistp(?:256|384|521)|"
    r"sk-(?:ssh-ed25519|ecdsa-sha2-nistp256)@openssh\.com)\s+"
    r"[A-Za-z0-9+/]+={0,3}(?:\s+.*)?$"
)


def hash_password(password: str) -> str:
    """Create a SHA-512 crypt hash suitable for preseed/autoinstall/kickstart."""
    if not password:
        raise ValueError("Password must not be empty")
    try:
        import crypt  # Unix only

        result = crypt.crypt(password, crypt.mksalt(crypt.METHOD_SHA512))
        if result and result.startswith("$6$"):
            return result
    except (ImportError, AttributeError, OSError, TypeError, ValueError):
        # Python 3.13+ has no stdlib crypt module; use the secure fallback below.
        ...

    # Python 3.13 removed ``crypt``.  OpenSSL implements the same SHA-512
    # crypt format and reads the secret from stdin, so it never appears in
    # the process list.  Do not replace this with a plain SHA-512 digest: that
    # looks like a crypt hash but cannot be used for a Linux login.
    salt = secrets.token_urlsafe(12).replace("-", "A").replace("_", "B")[:16]
    try:
        proc = subprocess.run(
            ["openssl", "passwd", "-6", "-salt", salt, "-stdin"],
            input=password + "\n",
            text=True,
            check=True,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("No secure SHA-512 password hashing backend is available") from exc
    result = proc.stdout.strip()
    if not result.startswith("$6$"):
        raise RuntimeError("Password hashing backend returned an invalid result")
    return result


def validate_ssh_public_key(pub_line: str) -> str:
    """Validate and normalize a single OpenSSH public-key line.

    Private keys, options before the key type, multiline input, and unusually
    large values are deliberately rejected.  The installer only needs plain
    public keys for ``authorized_keys``.
    """

    value = pub_line.strip()
    if not value or "\n" in value or "\r" in value or len(value) > 16_384:
        raise ValueError("Invalid SSH public key")
    if not _SSH_KEY_RE.fullmatch(value):
        raise ValueError("Unsupported or malformed SSH public key")
    if fingerprint_ssh_key(value) == "invalid":
        raise ValueError("Invalid SSH public key payload")
    return value


def fingerprint_ssh_key(pub_line: str) -> str:
    parts = pub_line.strip().split()
    if len(parts) < 2:
        return "invalid"
    try:
        import base64

        raw = base64.b64decode(parts[1], validate=True)
        if len(raw) < 8:
            return "invalid"
        algorithm_length = int.from_bytes(raw[:4], "big")
        algorithm = raw[4 : 4 + algorithm_length].decode("ascii")
        if algorithm != parts[0]:
            return "invalid"
        digest = hashlib.sha256(raw).digest()
        fp = base64.b64encode(digest).decode().rstrip("=")
        return f"{parts[0]} SHA256:{fp}"
    except (UnicodeDecodeError, ValueError, binascii.Error):
        return "invalid"


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
            keys.append(validate_ssh_public_key(key))
    return keys


def fetch_github_keys(username: str) -> list[str]:
    import urllib.request

    url = f"https://github.com/{username}.keys"
    with urllib.request.urlopen(url, timeout=10) as resp:
        text = resp.read().decode()
    return [validate_ssh_public_key(line) for line in text.splitlines() if line.strip()]


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
