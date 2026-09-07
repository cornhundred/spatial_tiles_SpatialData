#!/usr/bin/env bash
# Set up the integration environment: editable installs of the three forks.
set -euo pipefail

cd "$(dirname "$0")"
export PATH="/opt/anaconda3/bin:$PATH"
PY="$PWD/.venv/bin/python"

echo "=== cwd: $PWD"
echo "=== uv: $(command -v uv)"

echo "=== 1/5 spatialdata (editable) ==="
uv pip install --python "$PY" -e ../spatialdata

echo "=== 2/5 spatialdata-io (editable) ==="
uv pip install --python "$PY" -e ../spatialdata-io

echo "=== 3/5 celldega JS deps ==="
( cd ../celldega && npm ci )

echo "=== 4/5 celldega (editable, dev+pre) ==="
uv pip install --python "$PY" -e "../celldega[dev,pre]"

echo "=== 5/5 extras ==="
uv pip install --python "$PY" pytest pytest-cov jupyterlab ipykernel huggingface_hub

echo "=== VERSIONS ==="
"$PY" - <<'PYEOF'
import spatialdata, spatialdata_io, celldega
print("spatialdata    ", spatialdata.__version__)
print("spatialdata_io ", spatialdata_io.__version__)
print("celldega       ", celldega.__version__)
PYEOF

echo "=== DONE ==="
