#!/usr/bin/env bash
# Project venv at ./.venv from requirements.txt, then the regression tests.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip >/dev/null
.venv/bin/python -m pip install -r requirements.txt
mkdir -p linux/out
.venv/bin/python -m pip freeze > "linux/out/pip-freeze-$(date -u +%Y%m%dT%H%M%SZ).txt"
.venv/bin/python -B -m unittest discover -s tests
echo "Activate with: . .venv/bin/activate"
