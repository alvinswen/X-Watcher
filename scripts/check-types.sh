#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PATH="$ROOT_DIR/.venv/bin:$PATH"
BASELINE_FILE="$ROOT_DIR/.mypy-baseline.txt"

cd "$ROOT_DIR"

echo "⏳ mypy 全仓检查中…"

if ! command -v mypy >/dev/null 2>&1 || ! command -v mypy-baseline >/dev/null 2>&1; then
    echo "❌ 类型检查工具未安装，请 pip install -e '.[dev]' 安装开发依赖后重试"
    exit 2
fi

if [ ! -f "$BASELINE_FILE" ]; then
    echo "❌ 基线文件缺失，请先 mypy src | mypy-baseline sync 生成 .mypy-baseline.txt"
    exit 2
fi

mypy_stdout="$(mktemp)"
mypy_stderr="$(mktemp)"
filter_stdout="$(mktemp)"
cleanup() {
    rm -f "$mypy_stdout" "$mypy_stderr" "$filter_stdout"
}
trap cleanup EXIT

mypy src >"$mypy_stdout" 2>"$mypy_stderr"
mypy_status=$?

if [ "$mypy_status" -ge 2 ]; then
    cat "$mypy_stdout"
    cat "$mypy_stderr" >&2
    exit "$mypy_status"
fi

mypy-baseline filter --allow-unsynced --no-colors <"$mypy_stdout" >"$filter_stdout"
filter_status=$?
cat "$filter_stdout"

fixed_count="$(awk '/^  fixed:/ {print $2}' "$filter_stdout" | tail -n 1)"
new_count="$(awk '/^  new:/ {print $2}' "$filter_stdout" | tail -n 1)"
unresolved_count="$(awk '/^  unresolved:/ {print $2}' "$filter_stdout" | tail -n 1)"

fixed_count="${fixed_count:-0}"
new_count="${new_count:-0}"
unresolved_count="${unresolved_count:-0}"

if [ "$new_count" -gt 0 ]; then
    echo "❌ 新增了 ${new_count} 个类型错，需修掉才能通过"
    exit 1
fi

if [ "$fixed_count" -gt 0 ]; then
    echo "✅ 0 新增类型错（基线内 ${unresolved_count} 个存量错仍冻结，${fixed_count} 个旧错已消化）"
    echo "可 mypy-baseline sync 收缩基线"
    echo "通过≠零债"
    exit 0
fi

if [ "$filter_status" -ne 0 ]; then
    exit "$filter_status"
fi

echo "✅ 0 新增类型错（基线内 ${unresolved_count} 个存量错已冻结）"
echo "通过≠零债"
