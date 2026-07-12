#!/usr/bin/env bash
# 门禁：全仓裸 mypy strict · 绿灯 = 全仓 0 类型债（CHG-027 起 · 基线记账机制已退役）
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PATH="$ROOT_DIR/.venv/bin:$PATH"

cd "$ROOT_DIR"

# SC-03 · mypy 未装：exit 2 + 可操作安装指引（pip/uv 双口径）
if ! command -v mypy >/dev/null 2>&1; then
    echo "❌ 类型检查工具未安装，请 pip install -e '.[dev]'（uv 环境：uv pip install -e '.[dev]'）安装开发依赖后重试"
    exit 2
fi

echo "⏳ mypy 全仓检查中…"

# stdout/stderr 直接透传（SC-02 错误列表 / SC-04 崩溃输出均原样可见）
mypy src
mypy_status=$?

# SC-01 · 0 类型错：绿灯
if [ "$mypy_status" -eq 0 ]; then
    echo "✅ 类型检查通过 · 全仓 0 类型债"
    exit 0
fi

# SC-02 · 有类型错（mypy exit 1）：红灯 + 提示语义收紧
if [ "$mypy_status" -eq 1 ]; then
    echo "❌ 发现类型错误（绿灯标准 = 全仓 0 类型债），请修复上方错误后重试"
    exit 1
fi

# SC-04 · mypy 自身崩溃（exit ≥2）：原样透传退出码（输出已在上方透传）
exit "$mypy_status"
