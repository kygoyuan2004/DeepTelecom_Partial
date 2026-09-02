#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  echo "Usage: ./scripts/setup_env.sh"
  echo "Create or update generator/.conda-env with the tested Python dependencies."
  echo "Environment: DEEPTELECOM_CONDA=/path/to/conda (optional)"
  exit 0
fi
if [[ $# -ne 0 ]]; then
  echo "Unknown argument: $1 (try --help)" >&2
  exit 2
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PACKAGE_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)
ENV_PREFIX="$PACKAGE_ROOT/.conda-env"

if [[ -x "$ENV_PREFIX/bin/python" ]]; then
  echo "Local environment already exists: $ENV_PREFIX"
  "$ENV_PREFIX/bin/python" -m pip install -r "$PACKAGE_ROOT/requirements.txt"
  exit 0
fi

if [[ -n "${DEEPTELECOM_CONDA:-}" ]]; then
  CONDA_BIN="$DEEPTELECOM_CONDA"
elif command -v conda >/dev/null 2>&1; then
  CONDA_BIN=$(command -v conda)
else
  echo "Conda/Miniforge is required. Add conda to PATH or set DEEPTELECOM_CONDA." >&2
  exit 1
fi

if [[ ! -x "$CONDA_BIN" ]]; then
  echo "Conda executable is not usable: $CONDA_BIN" >&2
  exit 1
fi

"$CONDA_BIN" create --yes --prefix "$ENV_PREFIX" python=3.11 pip
"$ENV_PREFIX/bin/python" -m pip install --upgrade pip
"$ENV_PREFIX/bin/python" -m pip install -r "$PACKAGE_ROOT/requirements.txt"
echo "Environment ready: $ENV_PREFIX"
echo "Run $PACKAGE_ROOT/scripts/preflight.py, then $PACKAGE_ROOT/scripts/run_smoke_test.sh"
