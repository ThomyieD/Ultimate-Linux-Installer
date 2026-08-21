#!/usr/bin/env bash
# Canonical ISO entry point.  Kept for Makefile/CI compatibility.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/scripts/build-iso-simple.sh" "$@"
