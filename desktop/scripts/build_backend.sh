#!/bin/bash
# 把 Python 后端（FastAPI + minihermes 内核）打包为独立可执行文件
# 产物：desktop/build/backend/minihermes-backend（electron-builder extraResources 携带）
set -e
cd "$(dirname "$0")/../.."   # minihermes 项目根（scripts/../..）

KERNEL_ROOT="$(pwd)"
VENV_PY="$KERNEL_ROOT/.venv/bin/python"
OUT_DIR="$KERNEL_ROOT/desktop/build/backend"

mkdir -p "$OUT_DIR"

# 统一打包 minihermes 发行版（core + cli + services + 包数据），不再逐个枚举子包
"$VENV_PY" -m PyInstaller --noconfirm --clean \
  --onefile \
  --name minihermes-backend \
  --paths "$KERNEL_ROOT/src" \
  --paths "$KERNEL_ROOT/desktop/backend" \
  --collect-submodules minihermes \
  --collect-data minihermes \
  --collect-submodules uvicorn \
  --collect-submodules anyio \
  --distpath "$OUT_DIR" \
  --workpath /tmp/mh_pyi_build \
  --specpath /tmp/mh_pyi_build \
  "$KERNEL_ROOT/desktop/backend/server.py"

echo "=== backend 打包完成: $OUT_DIR/minihermes-backend ==="
ls -lh "$OUT_DIR/"
