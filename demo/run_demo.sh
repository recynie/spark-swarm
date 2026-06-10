#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
echo "Installing dependencies..."
uv sync --quiet 2>/dev/null || true
exec uv run python demo/runner.py
