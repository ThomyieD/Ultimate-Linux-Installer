from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]
KEYRING_LIBRARY = REPOSITORY / "scripts" / "lib-debian-archive-keyring.sh"
ISO_BUILDER = REPOSITORY / "scripts" / "build-iso-simple.sh"
ISO_VERIFIER = REPOSITORY / "scripts" / "verify-iso-uefi.sh"

REQUIRED_FINGERPRINTS = (
    "04B54C3CDCA79751B16BC6B5225629DF75B188BD",
    "5E04A1E3223A19A20706E20F9904613D4CCE68C6",
    "41587F7DB8C774BCCF131416762F67A0B2C39DE4",
)
EXPECTED_SHA256 = "9ea7778e443144ca490668737a8ab22dd3e748bb99e805e22ec055abeb3c7fac"
EXPECTED_URL = (
    "https://deb.debian.org/debian/pool/main/d/debian-archive-keyring/"
    "debian-archive-keyring_2025.1_all.deb"
)


def _source_and_run(
    script: str,
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            "-c",
            f'set -euo pipefail; source "$1"; {script}',
            "bash",
            str(KEYRING_LIBRARY),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )


def _install_fake_gpg(bindir: Path, fingerprints: list[str]) -> None:
    """Deterministic offline stand-in for fingerprint listing only."""

    bindir.mkdir(parents=True, exist_ok=True)
    script = bindir / "gpg"
    body = ["#!/bin/sh", "set -eu"]
    for fingerprint in fingerprints:
        body.append(f"echo 'fpr:::::::::{fingerprint}:'")
    body.append("exit 0")
    script.write_text("\n".join(body) + "\n", encoding="utf-8")
    script.chmod(0o755)


def _path_with_fake_gpg(bindir: Path) -> str:
    return f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}"


def test_helper_pins_url_version_and_sha256() -> None:
    completed = _source_and_run(
        'printf "%s\\n" '
        '"$ULI_DEBIAN_ARCHIVE_KEYRING_URL" '
        '"$ULI_DEBIAN_ARCHIVE_KEYRING_VERSION" '
        '"$ULI_DEBIAN_ARCHIVE_KEYRING_SHA256"; '
        "uli_debian13_required_fingerprints"
    )
    assert completed.returncode == 0, completed.stderr
    lines = completed.stdout.strip().splitlines()
    assert lines[0] == EXPECTED_URL
    assert lines[1] == "2025.1"
    assert lines[2] == EXPECTED_SHA256
    assert lines[3:] == list(REQUIRED_FINGERPRINTS)


def test_wrong_package_checksum_is_rejected(tmp_path: Path) -> None:
    fake = tmp_path / "debian-archive-keyring_2025.1_all.deb"
    fake.write_bytes(b"not-the-official-package")

    completed = _source_and_run(
        'uli_debian_archive_keyring_verify_sha256 "$FAKE_DEB"',
        env={"FAKE_DEB": str(fake)},
    )
    assert completed.returncode != 0
    assert "SHA-256 mismatch" in completed.stderr


def test_fetch_rejects_local_override_with_wrong_hash(tmp_path: Path) -> None:
    fake = tmp_path / "wrong.deb"
    fake.write_bytes(b"tampered")
    dest = tmp_path / "out.deb"

    completed = _source_and_run(
        'uli_debian_archive_keyring_fetch "$DEST"',
        env={
            "ULI_DEBIAN_ARCHIVE_KEYRING_DEB_PATH": str(fake),
            "DEST": str(dest),
        },
    )
    assert completed.returncode != 0
    assert "SHA-256 mismatch" in completed.stderr
    assert not dest.exists()


def test_each_missing_debian13_fingerprint_aborts(tmp_path: Path) -> None:
    payload = tmp_path / "payload.pgp"
    payload.write_bytes(b"offline-fixture-keyring")

    for missing in REQUIRED_FINGERPRINTS:
        keep = [fp for fp in REQUIRED_FINGERPRINTS if fp != missing]
        bindir = tmp_path / f"bin-missing-{missing}"
        _install_fake_gpg(bindir, keep)

        completed = _source_and_run(
            'uli_debian_archive_keyring_require_fingerprints "$KR"',
            env={
                "KR": str(payload),
                "PATH": _path_with_fake_gpg(bindir),
            },
        )
        assert completed.returncode != 0, missing
        assert missing in completed.stderr


def test_require_fingerprints_accepts_complete_fixture(tmp_path: Path) -> None:
    payload = tmp_path / "payload.pgp"
    payload.write_bytes(b"offline-fixture-keyring")
    bindir = tmp_path / "bin-complete"
    _install_fake_gpg(bindir, list(REQUIRED_FINGERPRINTS))

    completed = _source_and_run(
        'uli_debian_archive_keyring_require_fingerprints "$KR"',
        env={
            "KR": str(payload),
            "PATH": _path_with_fake_gpg(bindir),
        },
    )
    assert completed.returncode == 0, completed.stderr


def test_absolute_symlink_escape_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside" / "debian-archive-keyring.pgp"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"host-or-escape-payload")
    keyrings = root / "usr" / "share" / "keyrings"
    keyrings.mkdir(parents=True)
    (keyrings / "debian-archive-keyring.gpg").symlink_to(outside)

    bindir = tmp_path / "bin-escape-abs"
    _install_fake_gpg(bindir, list(REQUIRED_FINGERPRINTS))

    completed = _source_and_run(
        'uli_debian_archive_keyring_resolve_payload "$ROOT"',
        env={
            "ROOT": str(root),
            "PATH": _path_with_fake_gpg(bindir),
        },
    )
    assert completed.returncode != 0
    assert "absolute" in completed.stderr.lower() or "refusing" in completed.stderr.lower()

    verify = _source_and_run(
        'uli_debian_archive_keyring_verify_installed "$ROOT"',
        env={
            "ROOT": str(root),
            "PATH": _path_with_fake_gpg(bindir),
        },
    )
    assert verify.returncode != 0


def test_relative_traversal_symlink_escape_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside" / "debian-archive-keyring.pgp"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"traversal-payload")
    keyrings = root / "usr" / "share" / "keyrings"
    keyrings.mkdir(parents=True)
    (keyrings / "debian-archive-keyring.gpg").symlink_to(
        "../../../../../outside/debian-archive-keyring.pgp"
    )

    bindir = tmp_path / "bin-escape-rel"
    _install_fake_gpg(bindir, list(REQUIRED_FINGERPRINTS))

    completed = _source_and_run(
        'uli_debian_archive_keyring_resolve_payload "$ROOT"',
        env={
            "ROOT": str(root),
            "PATH": _path_with_fake_gpg(bindir),
        },
    )
    assert completed.returncode != 0
    assert "unsafe" in completed.stderr.lower() or "refusing" in completed.stderr.lower()


def test_relative_basename_symlink_resolves_inside_keyring_dir(tmp_path: Path) -> None:
    root = tmp_path / "root"
    keyrings = root / "usr" / "share" / "keyrings"
    keyrings.mkdir(parents=True)
    payload = keyrings / "debian-archive-keyring.pgp"
    payload.write_bytes(b"in-tree-payload")
    (keyrings / "debian-archive-keyring.gpg").symlink_to("debian-archive-keyring.pgp")

    completed = _source_and_run(
        'uli_debian_archive_keyring_resolve_payload "$ROOT"',
        env={"ROOT": str(root)},
    )
    assert completed.returncode == 0, completed.stderr
    resolved = Path(completed.stdout.strip())
    assert resolved == payload.resolve()
    assert resolved.parent == keyrings.resolve()


def test_keyring_directory_symlink_escape_is_rejected(tmp_path: Path) -> None:
    """Reject when usr/share/keyrings itself is a symlink out of the rootfs."""

    root = tmp_path / "root"
    outside = tmp_path / "outside"
    outside.mkdir(parents=True)
    payload = outside / "debian-archive-keyring.pgp"
    payload.write_bytes(b"outside-payload")
    (outside / "debian-archive-keyring.gpg").symlink_to("debian-archive-keyring.pgp")

    share = root / "usr" / "share"
    share.mkdir(parents=True)
    (share / "keyrings").symlink_to(outside)

    bindir = tmp_path / "bin-dir-escape"
    _install_fake_gpg(bindir, list(REQUIRED_FINGERPRINTS))
    env = {
        "ROOT": str(root),
        "PATH": _path_with_fake_gpg(bindir),
    }

    resolved = _source_and_run(
        'uli_debian_archive_keyring_resolve_payload "$ROOT"',
        env=env,
    )
    assert resolved.returncode != 0
    assert (
        "symlinked" in resolved.stderr.lower()
        or "escapes rootfs" in resolved.stderr.lower()
        or "refusing" in resolved.stderr.lower()
    )

    verify = _source_and_run(
        'uli_debian_archive_keyring_verify_installed "$ROOT"',
        env=env,
    )
    assert verify.returncode != 0


def test_builder_and_verifier_share_helper_and_pre_squash_gate() -> None:
    builder = ISO_BUILDER.read_text(encoding="utf-8")
    verifier = ISO_VERIFIER.read_text(encoding="utf-8")
    helper = KEYRING_LIBRARY.read_text(encoding="utf-8")

    assert "lib-debian-archive-keyring.sh" in builder
    assert "uli_debian_archive_keyring_install_into_chroot" in builder
    assert "uli_debian_archive_keyring_verify_installed" in builder
    pack = 'mksquashfs "$CHROOT" "$IMG/live/filesystem.squashfs"'
    assert pack in builder
    assert builder.index("uli_debian_archive_keyring_verify_installed") < builder.index(
        pack
    )

    assert "lib-debian-archive-keyring.sh" in verifier
    assert "uli_debian_archive_keyring_verify_installed" in verifier

    assert EXPECTED_SHA256 in helper
    assert EXPECTED_SHA256 not in builder
    assert EXPECTED_SHA256 not in verifier
    for fingerprint in REQUIRED_FINGERPRINTS:
        assert fingerprint in helper
        assert fingerprint not in builder
        assert fingerprint not in verifier

    assert "uli_debian_archive_keyring_resolve_payload" in helper
    assert "Refusing absolute Debian archive keyring symlink" in helper
    assert "Refusing symlinked Debian archive keyring directory" in helper
    assert 'expected_dir="$canon_root/usr/share/keyrings"' in helper


def test_builder_requires_curl_dpkg_deb_and_gpg_early() -> None:
    builder = ISO_BUILDER.read_text(encoding="utf-8")
    need_block = builder.split("for tool in", 1)[1].split("do", 1)[0]
    for tool in ("curl", "dpkg-deb", "gpg"):
        assert tool in need_block
    assert builder.index("for tool in") < builder.index("debootstrap --arch=")


@pytest.mark.skipif(os.geteuid() != 0, reason="keyring install requires root ownership")
@pytest.mark.skipif(shutil.which("dpkg-deb") is None, reason="dpkg-deb is not installed")
@pytest.mark.skipif(shutil.which("gpg") is None, reason="gpg is not installed")
def test_install_into_chroot_sets_root_modes_and_fingerprints(tmp_path: Path) -> None:
    """Optional offline install when the pinned .deb is already present locally."""

    host_deb_candidates = list(
        Path("/var/cache/apt/archives").glob("debian-archive-keyring_2025.1*_all.deb")
    )
    official = None
    for candidate in host_deb_candidates:
        check = _source_and_run(
            'uli_debian_archive_keyring_verify_sha256 "$DEB"',
            env={"DEB": str(candidate)},
        )
        if check.returncode == 0:
            official = candidate
            break
    if official is None:
        pytest.skip("pinned debian-archive-keyring_2025.1 .deb is not cached locally")

    chroot = tmp_path / "chroot"
    work = tmp_path / "work"
    (chroot / "usr" / "share" / "keyrings").mkdir(parents=True)
    stale = chroot / "usr" / "share" / "keyrings" / "debian-archive-keyring.gpg"
    stale.write_bytes(b"stale")
    stale.chmod(0o666)

    completed = _source_and_run(
        'uli_debian_archive_keyring_install_into_chroot "$CHROOT" "$WORK"',
        env={
            "CHROOT": str(chroot),
            "WORK": str(work),
            "ULI_DEBIAN_ARCHIVE_KEYRING_DEB_PATH": str(official),
        },
    )
    assert completed.returncode == 0, completed.stderr

    keyring = chroot / "usr" / "share" / "keyrings" / "debian-archive-keyring.gpg"
    assert keyring.is_symlink()
    assert keyring.readlink() == Path("debian-archive-keyring.pgp")
    payload = keyring.parent / "debian-archive-keyring.pgp"
    assert payload.is_file() and not payload.is_symlink()
    assert payload.stat().st_uid == 0
    assert payload.stat().st_gid == 0
    assert stat.S_IMODE(payload.stat().st_mode) & 0o022 == 0


def test_sources_runtime_gpgv_rule_unchanged() -> None:
    sources = (REPOSITORY / "app" / "uli" / "install" / "sources.py").read_text(
        encoding="utf-8"
    )
    assert '["gpgv", "--keyring", str(keyring), str(temporary)]' in sources
    assert "if result.returncode != 0:" in sources
    assert "APT source signature verification failed" in sources
    assert "NO_PUBKEY" not in sources
    assert "returncode in" not in sources
