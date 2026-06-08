#!/usr/bin/env bash
# M-5 符号链接农场:把 se 治理源 store 链接进旧应用 src.* 命名空间(单一真值,零拷贝零漂移)。
# 用法:  bash scripts/link_se_stores.sh [se_root]   # 默认 se_root=~/development/x-watcher-se
#         bash scripts/link_se_stores.sh --unlink     # 只删本脚本建立的符号链接
set -euo pipefail

APP_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../src" && pwd)"

MODE="link"
SE_ROOT="$HOME/development/x-watcher-se"
if [[ "${1:-}" == "--unlink" ]]; then
  MODE="unlink"
elif [[ -n "${1:-}" ]]; then
  SE_ROOT="$1"
fi
SE_SRC="$SE_ROOT/src"

# 子项目 0 MANIFEST(相对 src/ 的路径;后续子项目在此追加本实体文件集)
MANIFEST=(
  "storage"                                                 # 底座整包(目录符号链接)
  "preference/infrastructure/schedule_store.py"             # ScheduleStore Protocol
  "preference/infrastructure/file_schedule_repository.py"   # FileScheduleStore
)

for rel in "${MANIFEST[@]}"; do
  src="$SE_SRC/$rel"
  dest="$APP_SRC/$rel"
  if [[ "$MODE" == "unlink" ]]; then
    if [[ -L "$dest" ]]; then rm "$dest"; echo "unlinked: src/$rel"; fi
    continue
  fi
  [[ -e "$src" ]] || { echo "ERROR: se 源不存在: $src" >&2; exit 1; }
  mkdir -p "$(dirname "$dest")"
  if [[ -L "$dest" ]]; then
    cur="$(readlink "$dest")"
    [[ "$cur" == "$src" ]] && { echo "ok (exists): src/$rel"; continue; }
    echo "ERROR: src/$rel 已是符号链接但指向 $cur(期望 $src)" >&2; exit 1
  fi
  [[ -e "$dest" ]] && { echo "ERROR: src/$rel 已存在非符号链接真身,拒绝覆盖" >&2; exit 1; }
  ln -s "$src" "$dest"
  echo "linked: src/$rel -> $src"
done
echo "done ($MODE)."
