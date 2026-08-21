#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd -- "$script_dir/.." && pwd -P)"
cd -- "$repo_root"

if [[ -n "${ULI_CHECK_PYTHON:-}" ]]; then
  python_cmd=("$ULI_CHECK_PYTHON")
elif [[ -x .venv/bin/python ]]; then
  python_cmd=(.venv/bin/python)
else
  python_cmd=(python3)
fi

"${python_cmd[@]}" -m pytest -q
"${python_cmd[@]}" -m ruff check app adapters tests
"${python_cmd[@]}" -m compileall -q app adapters
"${python_cmd[@]}" - <<'PY'
import json
from pathlib import Path

for path in sorted(Path("app/uli/i18n").glob("*.json")):
    json.loads(path.read_text(encoding="utf-8"))
json.loads(Path("schemas/installation_plan.schema.json").read_text(encoding="utf-8"))
PY

if command -v node >/dev/null 2>&1; then
  node --check app/uli/web/static/app.js
fi

bash -n scripts/*.sh
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck \
    scripts/check.sh \
    scripts/build-iso.sh \
    scripts/build-iso-simple.sh \
    scripts/lib-runtime-bundle.sh \
    scripts/generate-theme-assets.sh \
    scripts/install-firefox-tarball.sh \
    scripts/lib-iso-uefi.sh \
    scripts/verify-iso-uefi.sh
fi

git diff --check
