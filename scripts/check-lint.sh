#!/usr/bin/env bash
# 门禁：全仓 ruff 全规则 · 绿灯 = 全仓 0 lint 债（CHG-038 起 · 与 check-types.sh 并排姊妹闸）
# 四态对齐 check-types.sh SC-01~04；SC-05 = 版本断言拒跑（无 CI 下防工具版本漂移致门禁语义漂）
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PATH="$ROOT_DIR/.venv/bin:$PATH"
cd "$ROOT_DIR"

# SC-03 · ruff 未装：exit 2 + 可操作安装指引（pip/uv 双口径）
if ! command -v ruff >/dev/null 2>&1; then
    echo "❌ lint 工具未安装，请 pip install -e '.[dev]'（uv 环境：uv pip install -e '.[dev]'）安装开发依赖后重试"
    exit 2
fi

# SC-05 · 版本钉死断言（fail-loud 拒跑）·唯一事实源 = pyproject.toml dev 依赖 "ruff==X.Y.Z"
PINNED="$(grep -Eo '"ruff==[0-9][^"]*"' pyproject.toml | head -1 | sed 's/"ruff==\(.*\)"/\1/')"
if [ -z "$PINNED" ]; then
    echo "❌ pyproject.toml 未找到 ruff 版本钉定行（期望 dev 依赖含 \"ruff==X.Y.Z\"）——门禁拒跑"
    exit 3
fi
ACTUAL="$(ruff --version | awk '{print $2}')"
if [ "$ACTUAL" != "$PINNED" ]; then
    echo "❌ ruff 版本不匹配：环境 $ACTUAL ≠ 钉定 ${PINNED}——请 pip install -e '.[dev]' 对齐后重试（拒跑防门禁语义漂移）"
    exit 3
fi

echo "⏳ ruff 全仓 lint 检查中…"

ruff check .
ruff_status=$?

# SC-01 · 0 lint 债：绿灯
if [ "$ruff_status" -eq 0 ]; then
    echo "✅ lint 检查通过 · 全仓 0 lint 债"
    exit 0
fi

# SC-02 · 有债：红灯 + 恢复路径指引
if [ "$ruff_status" -eq 1 ]; then
    echo "❌ 发现 lint 错误（绿灯标准 = 全仓 0 lint 债）：可先跑 ruff check . --fix 自动修复，再手修残余后重试"
    exit 1
fi

# SC-04 · ruff 自身崩溃（exit ≥2）：原样透传
exit "$ruff_status"

# —— ruff 版本升级路径（唯一合法流程·无 CI 兜底必须留痕）——
# 1) 改 pyproject.toml dev 依赖 "ruff==X.Y.Z" 一行（唯一事实源·本脚本自动读取）
# 2) pip install -e '.[dev]' 对齐环境
# 3) bash scripts/check-lint.sh 必须全绿（新版本引入新规则报错时先清完再提交）
# 4) 与相应代码改动同一 commit 提交
