#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"
if [[ -x "${ROOT}/.venv/bin/python" ]]; then
  exec "${ROOT}/.venv/bin/python" -m clawbridge.packaging build --root "${ROOT}" "$@"
fi
exec uv run --locked --project "${ROOT}" python -m clawbridge.packaging build --root "${ROOT}" "$@"
