from __future__ import annotations

import configparser
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]
RUNTIME_BUNDLE_LIBRARY = REPOSITORY / "scripts" / "lib-runtime-bundle.sh"
NETWORKMANAGER_ASSETS = REPOSITORY / "assets" / "networkmanager"
ISO_BUILDER = REPOSITORY / "scripts" / "build-iso-simple.sh"


def _write(path: Path, content: str = "fixture\n", mode: int = 0o666) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_live_image_uses_networkmanager_runtime_resolver() -> None:
    source = ISO_BUILDER.read_text(encoding="utf-8")

    assert 'ln -s ../run/NetworkManager/resolv.conf "$CHROOT/etc/resolv.conf"' in source


@pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync is not installed")
def test_runtime_bundle_is_allowlisted_and_has_fixed_permissions(tmp_path: Path) -> None:
    source = tmp_path / "source"
    chroot = tmp_path / "chroot"

    _write(source / "pyproject.toml", "[build-system]\n", 0o777)
    _write(source / "README.md", mode=0o777)
    _write(source / "LICENSE", mode=0o777)
    _write(source / "app" / "uli" / "main.py", mode=0o777)
    _write(source / "app" / "uli" / "__pycache__" / "main.pyc", mode=0o666)
    _write(source / "app" / "ultimate_linux_installer.egg-info" / "PKG-INFO")
    _write(source / "schemas" / "installation_plan.schema.json", "{}\n", 0o666)
    _write(source / "adapters" / "debian" / "__init__.py", mode=0o777)
    _write(source / "themes" / "grub" / "uli-dark" / "theme.txt", mode=0o666)

    # These repository/development files must never enter the live source tree.
    _write(source / "AGENT-HANDOFF.md")
    _write(source / "tests" / "test_leak.py")
    _write(source / ".github" / "workflows" / "ci.yml")
    _write(source / "build" / "lib" / "leak.py")
    _write(source / ".pytest_cache" / "leak")

    # Reproduce the permissive modes that triggered the packaging finding.
    for directory in sorted(source.rglob("*")):
        if directory.is_dir():
            directory.chmod(0o777)
    (source / "adapters").chmod(0o707)

    expected_uid = os.getuid()
    bundle_owner = f"{os.getuid()}:{os.getgid()}"
    if os.geteuid() == 0:
        # Also prove that a checkout owned by a CI-style non-root account is
        # remapped to root when the canonical root-only builder copies it.
        for path in [*source.rglob("*"), source]:
            os.chown(path, 65534, 65534)
        expected_uid = 0
        bundle_owner = "root:root"

    env = os.environ.copy()
    env["BUNDLE_SOURCE"] = str(source)
    env["BUNDLE_CHROOT"] = str(chroot)
    env["BUNDLE_OWNER"] = bundle_owner
    subprocess.run(
        [
            "bash",
            "-c",
            (
                'set -euo pipefail; umask 000; source "$1"; '
                'uli_install_runtime_bundle "$BUNDLE_SOURCE" "$BUNDLE_CHROOT" '
                '"$BUNDLE_OWNER"; '
                'uli_harden_runtime_bundle "$BUNDLE_CHROOT" "$BUNDLE_OWNER"'
            ),
            "bash",
            str(RUNTIME_BUNDLE_LIBRARY),
        ],
        check=True,
        env=env,
    )

    runtime_roots = [
        chroot / "opt" / "uli" / "src",
        chroot / "opt" / "uli" / "adapters",
        chroot / "usr" / "share" / "uli" / "themes",
    ]
    for runtime_root in runtime_roots:
        assert _mode(runtime_root) == 0o755
        assert runtime_root.stat().st_uid == expected_uid
        for path in runtime_root.rglob("*"):
            assert path.stat().st_uid == expected_uid, path
            if path.is_dir():
                assert _mode(path) == 0o755, path
            elif path.is_file():
                assert _mode(path) == 0o644, path

    source_bundle = chroot / "opt" / "uli" / "src"
    assert (source_bundle / "app" / "uli" / "main.py").is_file()
    assert (source_bundle / "schemas" / "installation_plan.schema.json").is_file()
    assert not (source_bundle / "AGENT-HANDOFF.md").exists()
    assert not (source_bundle / "tests").exists()
    assert not (source_bundle / ".github").exists()
    assert not (source_bundle / "build").exists()
    assert not (source_bundle / ".pytest_cache").exists()
    assert not (source_bundle / "app" / "uli" / "__pycache__").exists()
    assert not (source_bundle / "app" / "ultimate_linux_installer.egg-info").exists()


def test_runtime_security_check_rejects_writable_non_symlink(tmp_path: Path) -> None:
    chroot = tmp_path / "chroot"
    unsafe_file = chroot / "opt" / "uli" / "venv" / "unsafe.py"
    theme_file = chroot / "usr" / "share" / "uli" / "themes" / "theme.txt"
    _write(unsafe_file, mode=0o664)
    _write(theme_file, mode=0o644)

    completed = subprocess.run(
        [
            "bash",
            "-c",
            (
                'set -euo pipefail; source "$1"; '
                'uli_verify_runtime_bundle_security "$BUNDLE_CHROOT" "$BUNDLE_UID"'
            ),
            "bash",
            str(RUNTIME_BUNDLE_LIBRARY),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "BUNDLE_CHROOT": str(chroot),
            "BUNDLE_UID": str(os.getuid()),
        },
    )

    assert completed.returncode != 0
    assert "Unsafe runtime ownership or mode" in completed.stderr
    assert str(unsafe_file) in completed.stderr


def test_runtime_executables_are_set_explicitly_by_the_builder() -> None:
    builder = (REPOSITORY / "scripts" / "build-iso-simple.sh").read_text(
        encoding="utf-8"
    )

    # One copy feeds pip, the second removes build/egg-info generated by pip
    # before the source tree is packed into the ISO.
    assert builder.count('uli_install_runtime_bundle "$ROOT" "$CHROOT" root:root') == 2
    for runtime_executable in ("uli", "uli-start", "uli-boot-marker"):
        assert f'chmod 755 "$CHROOT/usr/local/bin/{runtime_executable}"' in builder
    assert 'chmod 755 "$CHROOT/etc/xdg/openbox/autostart"' in builder


def _read_keyfile(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path, encoding="utf-8")
    return parser


def test_live_networkmanager_manages_wired_and_wifi_devices() -> None:
    config = _read_keyfile(NETWORKMANAGER_ASSETS / "99-uli-live-network.conf")

    assert config["main"]["dns"] == "default"
    assert config["main"]["rc-manager"] == "file"
    assert config["ifupdown"].getboolean("managed") is True
    unmanaged = {
        item.strip() for item in config["keyfile"]["unmanaged-devices"].split(",")
    }
    assert "*" in unmanaged
    assert "except:type:ethernet" in unmanaged
    assert "except:type:wifi" in unmanaged
    assert config["device-uli-live-ethernet"]["match-device"] == "type:ethernet"
    assert config["device-uli-live-ethernet"].getboolean("managed") is True
    assert config["device-uli-live-wifi"]["match-device"] == "type:wifi"
    assert config["device-uli-live-wifi"].getboolean("managed") is True


def test_live_wired_profile_is_generic_autoconnecting_dhcp() -> None:
    profile = _read_keyfile(NETWORKMANAGER_ASSETS / "uli-wired-dhcp.nmconnection")
    connection = profile["connection"]

    assert connection["type"] == "ethernet"
    assert connection.getboolean("autoconnect") is True
    assert connection.getint("autoconnect-priority") > 0
    assert connection.getint("autoconnect-retries") == 0
    assert connection.getint("multi-connect") == 3
    assert "interface-name" not in connection
    assert "mac-address" not in profile["ethernet"]
    assert profile["ipv4"]["method"] == "auto"
    assert profile["ipv6"]["method"] == "auto"


def test_builder_installs_live_network_files_with_safe_modes() -> None:
    builder = (REPOSITORY / "scripts" / "build-iso-simple.sh").read_text(
        encoding="utf-8"
    )

    assert (
        'install -D -o root -g root -m 0644 \\\n'
        '  "$ROOT/assets/networkmanager/99-uli-live-network.conf"'
    ) in builder
    assert (
        'install -D -o root -g root -m 0600 \\\n'
        '  "$ROOT/assets/networkmanager/uli-wired-dhcp.nmconnection"'
    ) in builder
    assert 'uli_install_runtime_bundle "$ROOT" "$CHROOT" root:root' in builder
    assert 'uli_verify_runtime_bundle_security "$CHROOT"' in builder
