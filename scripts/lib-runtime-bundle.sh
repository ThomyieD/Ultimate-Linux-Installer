#!/usr/bin/env bash
# Helpers for copying only the files required by the live runtime.  The source
# checkout may have permissive or otherwise unusual modes; none of those modes
# are allowed to leak into the root-owned runtime trees.

uli_runtime_rsync_filters() {
  printf '%s\n' \
    "--exclude=__pycache__/" \
    "--exclude=*.py[cod]" \
    "--exclude=*.egg-info/" \
    "--exclude=.pytest_cache/" \
    "--exclude=.ruff_cache/" \
    "--exclude=.mypy_cache/" \
    "--exclude=.tox/" \
    "--exclude=.nox/" \
    "--exclude=.coverage" \
    "--exclude=coverage.xml" \
    "--exclude=htmlcov/" \
    "--exclude=build/" \
    "--exclude=dist/"
}

uli_install_runtime_bundle() {
  local root="${1:?repository root is required}"
  local chroot="${2:?chroot path is required}"
  local owner="${3:-root:root}"
  local source_target="$chroot/opt/uli/src"
  local adapter_target="$chroot/opt/uli/adapters"
  local theme_target="$chroot/usr/share/uli/themes"
  local -a filters=()

  if [[ "$root" != /* || "$chroot" != /* ]]; then
    echo "Runtime bundle paths must be absolute." >&2
    return 2
  fi
  if [[ ! -d "$root/app/uli" || ! -d "$root/adapters" || \
        ! -d "$root/schemas" || ! -d "$root/themes/grub" ]]; then
    echo "Repository is missing required runtime source directories." >&2
    return 2
  fi
  if [[ ! -f "$root/pyproject.toml" || ! -f "$root/README.md" || \
        ! -f "$root/LICENSE" ]]; then
    echo "Repository is missing required runtime metadata." >&2
    return 2
  fi

  mapfile -t filters < <(uli_runtime_rsync_filters)
  install -d -m 0755 "$source_target" "$adapter_target" "$theme_target"

  # Use an allowlist for the pip source tree.  In particular, this deliberately
  # omits handoff notes, CI configuration, tests, build output and repository
  # metadata instead of trying to enumerate every possible development file.
  rsync -rlptog --delete --delete-excluded --chown="$owner" \
    --chmod=D0755,F0644 \
    "${filters[@]}" \
    --include='/app/***' \
    --include='/schemas/***' \
    --include='/pyproject.toml' \
    --include='/README.md' \
    --include='/LICENSE' \
    --exclude='*' \
    "$root/" "$source_target/"

  rsync -rlptog --delete --delete-excluded --chown="$owner" \
    --chmod=D0755,F0644 \
    "${filters[@]}" \
    "$root/adapters/" "$adapter_target/"
  rsync -rlptog --delete --delete-excluded --chown="$owner" \
    --chmod=D0755,F0644 \
    "${filters[@]}" \
    "$root/themes/grub/" "$theme_target/"
}

uli_harden_runtime_bundle() {
  local chroot="${1:?chroot path is required}"
  local owner="${2:-root:root}"
  local path

  if [[ "$chroot" != /* ]]; then
    echo "Chroot path must be absolute." >&2
    return 2
  fi

  # pip may add metadata below src after the initial copy.  Normalize again
  # immediately before packaging so no caller umask or generated mode matters.
  for path in \
    "$chroot/opt/uli/src" \
    "$chroot/opt/uli/adapters" \
    "$chroot/usr/share/uli/themes"; do
    if [[ ! -d "$path" ]]; then
      echo "Runtime bundle directory is missing: $path" >&2
      return 2
    fi
    chown -R -- "$owner" "$path"
    find "$path" -type d -exec chmod 0755 {} +
    find "$path" -type f -exec chmod 0644 {} +
  done
}

uli_verify_runtime_bundle_security() {
  local chroot="${1:?chroot path is required}"
  local expected_uid="${2:-0}"
  local path bad

  if [[ "$chroot" != /* || ! "$expected_uid" =~ ^[0-9]+$ ]]; then
    echo "Runtime security check requires an absolute chroot and numeric UID." >&2
    return 2
  fi

  for path in "$chroot/opt/uli" "$chroot/usr/share/uli/themes"; do
    if [[ ! -d "$path" ]]; then
      echo "Runtime security root is missing: $path" >&2
      return 1
    fi
    if ! bad="$(
      find "$path" -xdev ! -type l \
        \( ! -uid "$expected_uid" -o -perm /022 \) -print -quit
    )"; then
      echo "Could not verify runtime ownership and modes below $path." >&2
      return 1
    fi
    if [[ -n "$bad" ]]; then
      echo "Unsafe runtime ownership or mode; refusing to build ISO:" >&2
      stat -c '%U:%G %a %n' -- "$bad" >&2 || printf '%s\n' "$bad" >&2
      return 1
    fi
  done
}
