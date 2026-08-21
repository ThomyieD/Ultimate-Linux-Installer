#!/usr/bin/env bash
# Canonical Debian archive keyring trust anchors for ULI ISO builds.
# ADR-003: keys come from a version-pinned, hashed artefact — never from an
# unverified HTTPS fetch alone, and never via maintainer scripts.

# Fixed package identity (Debian 13 / trixie era).
ULI_DEBIAN_ARCHIVE_KEYRING_VERSION="2025.1"
ULI_DEBIAN_ARCHIVE_KEYRING_DEB="debian-archive-keyring_${ULI_DEBIAN_ARCHIVE_KEYRING_VERSION}_all.deb"
ULI_DEBIAN_ARCHIVE_KEYRING_URL="https://deb.debian.org/debian/pool/main/d/debian-archive-keyring/${ULI_DEBIAN_ARCHIVE_KEYRING_DEB}"
ULI_DEBIAN_ARCHIVE_KEYRING_SHA256="9ea7778e443144ca490668737a8ab22dd3e748bb99e805e22ec055abeb3c7fac"

# Primary Debian 13 fingerprints (ftp-master.debian.org/keys.html).
ULI_DEBIAN13_ARCHIVE_FINGERPRINT="04B54C3CDCA79751B16BC6B5225629DF75B188BD"
ULI_DEBIAN13_SECURITY_FINGERPRINT="5E04A1E3223A19A20706E20F9904613D4CCE68C6"
ULI_DEBIAN13_STABLE_FINGERPRINT="41587F7DB8C774BCCF131416762F67A0B2C39DE4"

uli_debian13_required_fingerprints() {
  printf '%s\n' \
    "$ULI_DEBIAN13_ARCHIVE_FINGERPRINT" \
    "$ULI_DEBIAN13_SECURITY_FINGERPRINT" \
    "$ULI_DEBIAN13_STABLE_FINGERPRINT"
}

uli_debian_archive_keyring_path() {
  local root="${1:?chroot or rootfs path is required}"
  printf '%s\n' "$root/usr/share/keyrings/debian-archive-keyring.gpg"
}

# Only relative single-basename symlink targets are allowed (as shipped by the
# pinned Debian package: debian-archive-keyring.gpg -> debian-archive-keyring.pgp).
uli_debian_archive_keyring_symlink_target_ok() {
  local target="${1:?}"
  [[ "$target" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]
}

# Resolve the effective keyring payload and prove it stays inside
# <root>/usr/share/keyrings. Absolute links, .. traversal, and a symlinked
# keyrings directory are fail-closed.
uli_debian_archive_keyring_resolve_payload() {
  local root="${1:?chroot or rootfs path is required}"
  local canon_root expected_dir keyring link_target payload canon_dir canon_payload

  if [[ "$root" != /* ]]; then
    echo "Root path must be absolute." >&2
    return 2
  fi
  if [[ ! -d "$root" ]]; then
    echo "Root path is not a directory: $root" >&2
    return 1
  fi

  canon_root="$(realpath -e -- "$root")"
  expected_dir="$canon_root/usr/share/keyrings"

  if [[ -L "$expected_dir" ]]; then
    echo "Refusing symlinked Debian archive keyring directory: $expected_dir" >&2
    return 1
  fi
  if [[ ! -d "$expected_dir" ]]; then
    echo "Debian archive keyring directory missing: $expected_dir" >&2
    return 1
  fi
  canon_dir="$(realpath -e -- "$expected_dir")"
  if [[ "$canon_dir" != "$expected_dir" ]]; then
    echo "Debian archive keyring directory escapes rootfs: $canon_dir (expected $expected_dir)" >&2
    return 1
  fi

  keyring="$expected_dir/debian-archive-keyring.gpg"

  if [[ -L "$keyring" ]]; then
    link_target="$(readlink -- "$keyring")"
    if [[ "$link_target" == /* ]]; then
      echo "Refusing absolute Debian archive keyring symlink: $link_target" >&2
      return 1
    fi
    if ! uli_debian_archive_keyring_symlink_target_ok "$link_target"; then
      echo "Refusing unsafe Debian archive keyring symlink target: $link_target" >&2
      return 1
    fi
    payload="$expected_dir/$link_target"
  elif [[ -f "$keyring" ]]; then
    payload="$keyring"
  else
    echo "Effective Debian archive keyring missing: $keyring" >&2
    return 1
  fi

  # Do not follow further symlinks on the payload (blocks link chains).
  if [[ -L "$payload" || ! -f "$payload" ]]; then
    echo "Debian archive keyring payload must be a regular file: $payload" >&2
    return 1
  fi

  canon_payload="$(realpath -e -- "$payload")"
  case "$canon_payload" in
    "$expected_dir"/*) ;;
    *)
      echo "Debian archive keyring payload escapes keyring directory: $canon_payload" >&2
      return 1
      ;;
  esac

  printf '%s\n' "$canon_payload"
}

uli_debian_archive_keyring_verify_sha256() {
  local deb="${1:?debian-archive-keyring .deb path is required}"
  if [[ ! -f "$deb" ]]; then
    echo "Debian archive keyring package is missing: $deb" >&2
    return 1
  fi
  if ! printf '%s  %s\n' "$ULI_DEBIAN_ARCHIVE_KEYRING_SHA256" "$deb" \
    | sha256sum --check --status; then
    echo "Debian archive keyring SHA-256 mismatch for $deb" >&2
    echo "Expected: $ULI_DEBIAN_ARCHIVE_KEYRING_SHA256" >&2
    return 1
  fi
}

uli_debian_archive_keyring_fetch() {
  local dest="${1:?destination .deb path is required}"
  local source_path="${ULI_DEBIAN_ARCHIVE_KEYRING_DEB_PATH:-}"

  mkdir -p "$(dirname "$dest")"
  if [[ -n "$source_path" ]]; then
    if [[ ! -f "$source_path" ]]; then
      echo "ULI_DEBIAN_ARCHIVE_KEYRING_DEB_PATH is not a file: $source_path" >&2
      return 1
    fi
    cp -f -- "$source_path" "$dest"
  else
    curl -fsSL --proto '=https' --tlsv1.2 \
      -o "$dest" "$ULI_DEBIAN_ARCHIVE_KEYRING_URL" || {
      rm -f -- "$dest"
      echo "Failed to download $ULI_DEBIAN_ARCHIVE_KEYRING_URL" >&2
      return 1
    }
  fi
  if ! uli_debian_archive_keyring_verify_sha256 "$dest"; then
    rm -f -- "$dest"
    return 1
  fi
}

uli_debian_archive_keyring_list_fingerprints() {
  local keyring="${1:?keyring path is required}"
  if [[ ! -f "$keyring" || -L "$keyring" ]]; then
    echo "Keyring payload must be a regular file: $keyring" >&2
    return 1
  fi
  gpg --batch --no-default-keyring --keyring "$keyring" \
    --list-keys --with-colons --fingerprint 2>/dev/null \
    | awk -F: '/^fpr:/{print toupper($10)}'
}

uli_debian_archive_keyring_require_fingerprints() {
  local keyring="${1:?keyring path is required}"
  local present_file missing=0 fp

  present_file="$(mktemp)"
  if ! uli_debian_archive_keyring_list_fingerprints "$keyring" >"$present_file"; then
    rm -f -- "$present_file"
    echo "Unable to list fingerprints from $keyring" >&2
    return 1
  fi

  while IFS= read -r fp; do
    [[ -n "$fp" ]] || continue
    if ! grep -Fxq -- "$fp" "$present_file"; then
      echo "Missing required Debian 13 archive fingerprint: $fp" >&2
      missing=1
    fi
  done < <(uli_debian13_required_fingerprints)
  rm -f -- "$present_file"

  if [[ "$missing" -ne 0 ]]; then
    return 1
  fi
}

uli_debian_archive_keyring_verify_installed() {
  local root="${1:?chroot or rootfs path is required}"
  local payload owner mode

  payload="$(uli_debian_archive_keyring_resolve_payload "$root")" || return

  owner="$(stat -c '%u:%g' "$payload")"
  mode="$(stat -c '%a' "$payload")"
  if [[ "$owner" != "0:0" ]]; then
    echo "Debian archive keyring must be root:root (found $owner): $payload" >&2
    return 1
  fi
  # Not group- or world-writable (0644 / 0444 are acceptable).
  if [[ "$((8#$mode & 022))" -ne 0 ]]; then
    echo "Debian archive keyring has unsafe mode $mode: $payload" >&2
    return 1
  fi

  uli_debian_archive_keyring_require_fingerprints "$payload"
}

uli_debian_archive_keyring_install_into_chroot() {
  local chroot="${1:?chroot path is required}"
  local workdir="${2:?scratch workdir is required}"
  local deb extract src dst path link_target

  if [[ "$chroot" != /* || "$workdir" != /* ]]; then
    echo "Keyring install paths must be absolute." >&2
    return 2
  fi
  if [[ ! -d "$chroot" || "$chroot" == "/" ]]; then
    echo "Refusing unsafe chroot for keyring install: $chroot" >&2
    return 2
  fi

  mkdir -p "$workdir"
  deb="$workdir/$ULI_DEBIAN_ARCHIVE_KEYRING_DEB"
  extract="$workdir/extract"
  rm -rf -- "$extract"
  mkdir -p "$extract"

  uli_debian_archive_keyring_fetch "$deb"
  # Extract only; never run package maintainer scripts.
  dpkg-deb -x "$deb" "$extract"

  src="$extract/usr/share/keyrings"
  dst="$chroot/usr/share/keyrings"
  if [[ ! -d "$src" ]]; then
    echo "Extracted package lacks usr/share/keyrings" >&2
    return 1
  fi
  if [[ ! -f "$src/debian-archive-keyring.pgp" && \
        ! -f "$src/debian-archive-keyring.gpg" ]]; then
    echo "Extracted package lacks debian-archive-keyring payload" >&2
    return 1
  fi

  install -d -o root -g root -m 0755 "$dst"
  # Drop Ubuntu/Noble leftovers for the same paths before installing the pin.
  find "$dst" -maxdepth 1 \( -type f -o -type l \) \
    -name 'debian-archive-*' -delete

  # Copy public keyring material only (files + safe relative symlinks).
  while IFS= read -r -d '' path; do
    local rel base
    rel="${path#"$src"/}"
    base="$(basename "$rel")"
    case "$base" in
      debian-archive-*) ;;
      *) continue ;;
    esac
    if [[ -L "$path" ]]; then
      link_target="$(readlink -- "$path")"
      if ! uli_debian_archive_keyring_symlink_target_ok "$link_target"; then
        echo "Refusing unsafe packaged keyring symlink: $base -> $link_target" >&2
        return 1
      fi
      ln -sfn -- "$link_target" "$dst/$base"
      chown -h root:root "$dst/$base"
    elif [[ -f "$path" ]]; then
      install -o root -g root -m 0644 "$path" "$dst/$base"
    fi
  done < <(find "$src" -maxdepth 1 \( -type f -o -type l \) -print0)

  uli_debian_archive_keyring_verify_installed "$chroot"
}
