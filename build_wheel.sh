#!/bin/bash
# 构建 minihermes wheel 包
# 使用方法: cd miniHermes && bash build_wheel.sh
# 产物: dist/minihermes-*.whl
# 说明: hatchling 直接打包 src/minihermes（含 cli/core/services/包数据），无复制 hack

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== 构建 wheel ==="
uv build --wheel -o dist/

echo ""
echo "=== 构建完成 ==="
ls -lh dist/*.whl 2>/dev/null
echo ""
echo "分发方式："
echo "  将 dist/ 下的 .whl 文件发给他人"
echo ""
echo "安装方式："
echo "  pip install dist/minihermes-*.whl"
echo "  # 或"
echo "  uv tool install dist/minihermes-*.whl"
echo ""
echo "使用方式："
echo "  minihermes    # 在任意目录的终端中输入"
