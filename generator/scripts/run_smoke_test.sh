#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  echo "Usage: ./scripts/run_smoke_test.sh"
  echo "Generate and verify one short sample on one GPU."
  echo "Environment: DEEPTELECOM_PYTHON=/path/to/python DEEPTELECOM_GPU_ID=0"
  exit 0
fi
if [[ $# -ne 0 ]]; then
  echo "Unknown argument: $1 (try --help)" >&2
  exit 2
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PACKAGE_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)
SMOKE_ROOT="$PACKAGE_ROOT/run/smoke_test"

if [[ -n "${DEEPTELECOM_PYTHON:-}" ]]; then
  PYTHON_BIN="$DEEPTELECOM_PYTHON"
elif [[ -x "$PACKAGE_ROOT/.conda-env/bin/python" ]]; then
  PYTHON_BIN="$PACKAGE_ROOT/.conda-env/bin/python"
else
  PYTHON_BIN=$(command -v python3)
fi

if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "nvidia-smi was not found; the Sionna RT smoke test requires one NVIDIA GPU." >&2
  exit 1
fi

# Deliberately use one explicit GPU. Override with DEEPTELECOM_GPU_ID.
GPU_ID=${DEEPTELECOM_GPU_ID:-0}
AVAILABLE_GPU_IDS=$(nvidia-smi --query-gpu=index --format=csv,noheader,nounits \
  | awk '{$1=$1; print}')
if ! grep -Fxq "$GPU_ID" <<<"$AVAILABLE_GPU_IDS"; then
  echo "GPU $GPU_ID is not available. Set DEEPTELECOM_GPU_ID to a valid index." >&2
  exit 1
fi
echo "Smoke test uses GPU $GPU_ID"
CUDA_VISIBLE_DEVICES="$GPU_ID" TF_FORCE_GPU_ALLOW_GROWTH=true \
  "$PYTHON_BIN" "$PACKAGE_ROOT/src/build_rt_uav_stft_dataset.py" \
  --root "$SMOKE_ROOT" \
  --config "$PACKAGE_ROOT/config/etoile.yaml" \
  --classes pitch30_v10 \
  --start-index 0 \
  --end-index 0 \
  --samples-per-class 1 \
  --snapshot-override 8 \
  --rt-snapshot-stride 2 \
  --max-new-samples 1 \
  --resume
"$PYTHON_BIN" "$PACKAGE_ROOT/src/verify_uav_kinematics.py" \
  --root "$SMOKE_ROOT" --verify-only
echo "Smoke test: PASS"
