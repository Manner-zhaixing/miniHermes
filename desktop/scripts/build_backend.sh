#!/bin/bash
# 把 Python 后端（FastAPI + minihermes 内核）打包为独立可执行文件
# 产物：build/backend/minihermes-backend（electron-builder extraResources 携带）
set -e
cd "$(dirname "$0")/../.."   # minihermes 项目根（scripts/../..）

KERNEL_ROOT="$(pwd)"
VENV_PY="$KERNEL_ROOT/.venv/bin/python"
OUT_DIR="$KERNEL_ROOT/minihermes-desktop/build/backend"

mkdir -p "$OUT_DIR"

"$VENV_PY" -m PyInstaller --noconfirm --clean \
  --onefile \
  --name minihermes-backend \
  --paths "$KERNEL_ROOT" \
  --collect-submodules uvicorn \
  --collect-submodules anyio \
  --collect-submodules tools \
  --collect-submodules cli \
  --collect-submodules skills \
  --collect-submodules renderer \
  --collect-submodules prompt \
  --collect-submodules agent \
  --collect-submodules provider \
  --collect-submodules context \
  --collect-submodules session \
  --collect-submodules approval \
  --collect-submodules config \
  --collect-submodules evolution \
  --distpath "$OUT_DIR" \
  --workpath /tmp/mh_pyi_build \
  --specpath /tmp/mh_pyi_build \
  "$KERNEL_ROOT/minihermes-desktop/backend/server.py"

echo "=== backend 打包完成: $OUT_DIR/minihermes-backend ==="
ls -lh "$OUT_DIR/"
