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

# 子项目 0+1 MANIFEST(相对 src/ 的路径;后续子项目在此追加本实体文件集)
MANIFEST=(
  "storage"                                                 # 底座整包(目录符号链接)
  "preference/infrastructure/schedule_store.py"             # ScheduleStore Protocol
  "preference/infrastructure/file_schedule_repository.py"   # FileScheduleStore
  "preference/infrastructure/follow_store.py"
  "preference/infrastructure/file_follow_repository.py"
  "preference/infrastructure/profile_store.py"
  "preference/infrastructure/file_profile_repository.py"
  "scraper/infrastructure/fetch_stats_store.py"
  "scraper/infrastructure/file_fetch_stats_repository.py"
  "scraper/infrastructure/article_store.py"
  "scraper/infrastructure/file_article_repository.py"
  "scraper/infrastructure/scheduler_log_store.py"
  "scraper/infrastructure/file_scheduler_log_repository.py"
  "scraper/domain/pagination.py"                            # Feed/Page:tweet store 依赖的 se-only 域模型
  "scraper/infrastructure/tweet_store.py"
  "scraper/infrastructure/file_tweet_repository.py"
  "summarization/infrastructure/summary_store.py"
  "summarization/infrastructure/file_summary_repository.py"
  "topic/infrastructure/topic_store.py"
  "topic/infrastructure/file_topic_repository.py"
  "topic/infrastructure/topic_task_store.py"
  "topic/infrastructure/file_topic_summary_task_repository.py"
  "user/infrastructure/user_store.py"
  "user/infrastructure/file_user_repository.py"
  "sync/infrastructure/export_serializers.py"              # 子项目5:FileExportStore 依赖的序列化器
  "sync/infrastructure/file_export_repository.py"          # 子项目5:FileExportStore
  "sync/infrastructure/file_import_repository.py"          # 子项目5:FileImportStore
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
