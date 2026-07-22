# X-Watcher 运维约定

本文记录文件存储模式下必须人工遵守的运行约束。使用进程管理器部署时，将 `pkill`/启动命令替换为对应的 stop/start 命令，但停手判据不变。

## 路径与解释器约定

本文**不假设仓库位于任何固定路径**（历史版本在多处写死 `cd code/X-Watcher`，在其它部署位置一律失败）。执行前先设好两个变量：

```bash
export XWATCHER_DATA_ROOT=/path/to/data_migrated   # 数据根，必设
export REPO_ROOT=/path/to/X-Watcher                # 仓库根，仅 import 项目代码的命令用得到
```

- **需要 import 项目代码**的命令（迁移脚本、`FileSummaryStore` 冒烟）必须用仓库虚拟环境：`"${REPO_ROOT}/.venv/bin/python"`，并从 `${REPO_ROOT}` 执行。
- **纯标准库**的自查脚本（末节「同一推文多条摘要自查 runbook」）只依赖 `${XWATCHER_DATA_ROOT}`，用 `python3` 即可，**可在任意工作目录执行**。该段落会被 `tests/summarization/test_chg042_monthly_shards.py` 逐字提取运行，且测试的工作目录并非仓库根——因此其中**禁止**出现 `cd`、相对路径解释器或任何 cwd 假设。

## 抓取与 MCP 翻译不得并发

文件存储目前只有进程内锁，没有跨进程锁。REST 抓取/导入与 MCP 摘要翻译可能由不同进程写同一数据根，因此同一实例上不得让抓取或导入与 MCP `save_summaries` 并发。启动前先排定互斥时段；修改 `MCP_SCRAPE_ENABLED` 后必须重启 MCP 进程才算生效。

## 摘要月分片迁移：10～15 分钟停手窗口

上线时序固定为：先停服务并迁移，核对通过后再切换和启动新代码。窗口期间网页后台与 Agent MCP 均不可用。窗口必须持续到条数与内容核对通过为止；窗口内禁止自动或人工重启 REST/MCP，因为启动期重建任务会与迁移互相干扰。

### 1. 窗口前准备

提前通知网页和 Agent 调用方。确认数据根和日志位置，并检查旧摘要文件存在：

```bash
DATA_ROOT="${XWATCHER_DATA_ROOT:?请先设置 XWATCHER_DATA_ROOT}"
REPO_ROOT="${REPO_ROOT:?请先设置 REPO_ROOT（仓库根）}"
cd "${REPO_ROOT}"
LOG_PATH="${LOG_FILE:-${REPO_ROOT}/logs/x-watcher.log}"
LEGACY="${DATA_ROOT}/summaries/summaries.json"
test -f "${LEGACY}"
```

先等所有已经进入 REST 的长耗时 `POST /api/admin/sync/import/execute` 请求结束；等待期间不要重新开始计时，也不要接受新导入。可在服务日志和调用方响应中确认最后一个请求已完成：

```bash
REPO_ROOT="${REPO_ROOT:?请先设置 REPO_ROOT（仓库根）}"
LOG_PATH="${LOG_FILE:-${REPO_ROOT}/logs/x-watcher.log}"
rg '/api/admin/sync/import/execute' "${LOG_PATH}"* | tail -20
```

### 2. 停手动作与三重证据确认已停

依次关停 MCP、关停 REST，再用三重证据确认两个进程都已退出。仅口头通知不算停手完成。

⚠️ **匹配模式必须对准真实命令行**：MCP 由 `.mcp.json` 以 `python -m src.cli.main mcp --transport stdio` 拉起，命令行中**不含** `x-watcher mcp` 子串。历史版本写的 `pkill -f '[x]-watcher mcp'` 既杀不掉进程，其后同模式的 `pgrep` 复查也匹配不到，于是打印「已停止」——**假阴性绿灯**，而进程还活着、还在写数据根，这正是迁移期间最危险的状态。若你的部署确实以 `x-watcher` 入口点启动，把下面两个 `*_PAT` 换成实际命令行即可，判据不变。

⚠️ **本节代码块请存盘后以 `bash <文件>` 执行，勿整段粘贴进终端**：块内 NG 分支以 `exit 1` 返回失败码，直接粘贴会关闭当前终端窗口，停手窗口内丢失终端的代价远高于平时。（循环已按 zsh/bash 通用写法处理，两种 shell 下判据一致。）

⚠️ **不要用 `pgrep -a`**：macOS 上 `-a` 意为 include process ancestors，并非 Linux 的 list full command line，输出只有 PID、不含命令行，与判读意图不符。需要看命令行时用 `ps -eo pid,ppid,stat,command | grep -E ...`。

```bash
DATA_ROOT="${XWATCHER_DATA_ROOT:?请先设置 XWATCHER_DATA_ROOT}"
LEGACY="${DATA_ROOT}/summaries/summaries.json"
MCP_PAT='src\.cli\.main mcp'
SRV_PAT='src\.cli\.main serve'

BEFORE="$(pgrep -f "${MCP_PAT}" || true; pgrep -f "${SRV_PAT}" || true)"
echo "停手前目标 PID: ${BEFORE:-（无）}"

pkill -TERM -f "${MCP_PAT}" || true
pkill -TERM -f "${SRV_PAT}" || true

# 证据一：原 PID 逐个消失（SIGTERM 后存在短暂退出竞态，最多等 10 秒）
# 必须用 while-read 而非 `for pid in ${BEFORE}`：zsh（macOS 默认登录 shell）不对
# 未加引号的参数展开做分词，for 写法会把多个 PID 当作一个词，ps 报错后被 `|| break`
# 误判为「已退出」——同时停 MCP + REST 恰是两个 PID，正是本节的常规路径。
while IFS= read -r pid; do
  [ -n "${pid}" ] || continue
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    ps -p "${pid}" >/dev/null 2>&1 || break
    sleep 1
  done
  if ps -p "${pid}" >/dev/null 2>&1; then
    echo "NG: PID ${pid} 仍未退出" >&2
    exit 1
  fi
done <<< "${BEFORE}"

# 证据二：按真实命令行模式复查无残留（含窗口内被误重启拉起的新进程）
if pgrep -f "${MCP_PAT}" >/dev/null 2>&1 || pgrep -f "${SRV_PAT}" >/dev/null 2>&1; then
  echo 'NG: 仍有 MCP/REST 进程在运行：' >&2
  ps -eo pid,ppid,stat,command | grep -E 'src\.cli\.main (mcp|serve)' | grep -v grep >&2
  exit 1
fi

# 证据三：数据文件无进程持有句柄。
# 定位：证据一、二的**补充**，不能单独作为「已停写」的判据。它抓的是长期持有句柄的
# 读者；本项目写路径走 atomic_replace（临时文件 + fsync + os.replace，见
# src/storage/atomic.py:33），最终文件在写入期间并不被持有句柄，实测对活写检出率为 0。
if command -v lsof >/dev/null 2>&1; then
  for f in "${LEGACY}" "${DATA_ROOT}"/summaries/*.jsonl "${DATA_ROOT}"/summaries/*.tmp; do
    [ -e "${f}" ] || continue
    if lsof -- "${f}" >/dev/null 2>&1; then
      echo "NG: ${f} 仍被进程持有句柄" >&2
      lsof -- "${f}" >&2
      exit 1
    fi
  done
  echo 'OK: MCP 与 REST 已停止（三重证据：原 PID 消失 · 无同名进程 · 数据文件无句柄占用）'
else
  echo '⚠️ lsof 不可用，证据三未执行 —— 停手判据降级为二重' >&2
  echo 'OK(降级): MCP 与 REST 已停止（二重证据：原 PID 消失 · 无同名进程；未验句柄占用）'
fi
```

⚠️ **停手后至窗口解除前，禁止调用任何 x-watcher MCP 工具**。Claude Code 等客户端的 stdio MCP 是**懒启动**：子进程被 `kill` 后不会自动重启（实测一个 15 分钟窗口内零自动拉起），但**任何一次工具调用都会即时按需拉起新进程**，加载调用那一刻磁盘上的代码。窗口内误调一次只读工具（哪怕只是 `get_system_status`），就等于凭空重启了 MCP —— 这正是下一段「禁止自动或人工重启 REST/MCP」要防的后果，而这条路径不经过任何显式的启动动作，极易被忽略。窗口内的一切核对与冒烟都必须走**独立解释器进程**（本文 §2～§3 及末节脚本均已满足），不得借道 MCP 工具。

反过来，窗口解除时**不需要**任何手动重连操作：调用一次只读工具即完成拉起，新进程会加载迁移后的代码。

从这一刻开始禁止服务重启。用下面命令连续观察两次旧文件的修改时间、大小和记录数；两次间隔两分钟且数值一致才算活写停止。第二次读数是本次迁移核对基准（N11），不是进窗口前的旧快照。

```bash
DATA_ROOT="${XWATCHER_DATA_ROOT:?请先设置 XWATCHER_DATA_ROOT}"
LEGACY="${DATA_ROOT}/summaries/summaries.json"
REPO_ROOT="${REPO_ROOT:?请先设置 REPO_ROOT（仓库根）}"
PYTHONPYCACHEPREFIX=$(mktemp -d) "${REPO_ROOT}/.venv/bin/python" - "${LEGACY}" <<'PY'
import json, pathlib, sys, time

path = pathlib.Path(sys.argv[1])
for turn in range(2):
    stat = path.stat()
    count = len(json.loads(path.read_text(encoding="utf-8")).get("summaries", {}))
    print(f"sample={turn + 1} mtime_ns={stat.st_mtime_ns} size={stat.st_size} records={count}")
    if turn == 0:
        time.sleep(120)
PY
```

### 3. 完整备份、预演和执行

记录窗口内确认已停后的基准，先做逐字节备份，再运行默认 dry-run。禁止使用起包快照的 `52,567` 作为现场基准。

```bash
DATA_ROOT="${XWATCHER_DATA_ROOT:?请先设置 XWATCHER_DATA_ROOT}"
LEGACY="${DATA_ROOT}/summaries/summaries.json"
REPO_ROOT="${REPO_ROOT:?请先设置 REPO_ROOT（仓库根）}"
BACKUP="${LEGACY}.pre-migration"
cp -p "${LEGACY}" "${BACKUP}"
cmp "${LEGACY}" "${BACKUP}"
PYTHONPYCACHEPREFIX=$(mktemp -d) "${REPO_ROOT}/.venv/bin/python" \
  "${REPO_ROOT}/scripts/migrate_summaries_to_monthly_shards.py" --data-root "${DATA_ROOT}" --dry-run
PYTHONPYCACHEPREFIX=$(mktemp -d) "${REPO_ROOT}/.venv/bin/python" \
  "${REPO_ROOT}/scripts/migrate_summaries_to_monthly_shards.py" --data-root "${DATA_ROOT}" --execute
```

脚本只有在 A～C 结构核对和 D 段真实运行时读路径全部通过后，才把原文件改名为 `summaries.json.migrated-<时间戳>`；它不会修改原文件内容。已有月分片时默认拒绝，确认是在清理半成品后重跑才可加 `--force`。

查看所有分片的修改时间、大小和非空记录数：

```bash
DATA_ROOT="${XWATCHER_DATA_ROOT:?请先设置 XWATCHER_DATA_ROOT}"
LEGACY="${DATA_ROOT}/summaries/summaries.json"
REPO_ROOT="${REPO_ROOT:?请先设置 REPO_ROOT（仓库根）}"
PYTHONPYCACHEPREFIX=$(mktemp -d) "${REPO_ROOT}/.venv/bin/python" - "${DATA_ROOT}" <<'PY'
import pathlib, sys

root = pathlib.Path(sys.argv[1])
total = 0
for path in sorted((root / "summaries").glob("*.jsonl")):
    stat = path.stat()
    count = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    total += count
    print(f"{path.name} mtime_ns={stat.st_mtime_ns} size={stat.st_size} records={count}")
print(f"total_records={total}")
PY
```

### 4. 失败与真实回滚

迁移、A～D 核对或第一栏冒烟任一失败：不要解除窗口，不要启动服务。删除全部半成品月分片，将脚本生成的归档文件改回原名，然后核对它与迁移前备份逐字节一致。回滚只允许在停手窗口内执行；解除窗口后再回滚会丢掉恢复服务后的新写入。

```bash
DATA_ROOT="${XWATCHER_DATA_ROOT:?请先设置 XWATCHER_DATA_ROOT}"
LEGACY="${DATA_ROOT}/summaries/summaries.json"
BACKUP="${LEGACY}.pre-migration"
ARCHIVE=$(ls -1t "${DATA_ROOT}"/summaries/summaries.json.migrated-* | head -1)
rm -f "${DATA_ROOT}"/summaries/*.jsonl
mv "${ARCHIVE}" "${LEGACY}"
cmp "${LEGACY}" "${BACKUP}"
```

只有迁移核对与第一栏 B1～B4 全绿后，才部署并启动新版本。归档与迁移前备份都先保留；确认稳定后再人工决定清理，禁止脚本自动删除。

### 5. 回存与导入记录位置

MCP 回存的审计记录由 `xwatcher.audit` 写入 `LOG_FILE`（默认 `logs/x-watcher.log`）；REST 导入执行可在同一服务日志的 Uvicorn access 记录中按路径查找。重复摘要导入的跳过原因也写在该日志中，包含 `tweet_id`、外来 `summary_id` 和已有 `summary_id`。

```bash
REPO_ROOT="${REPO_ROOT:?请先设置 REPO_ROOT（仓库根）}"
LOG_PATH="${LOG_FILE:-${REPO_ROOT}/logs/x-watcher.log}"
rg 'AUDIT .*tool=save_summaries|/api/admin/sync/import/execute|跳过重复摘要导入' \
  "${LOG_PATH}"*
```

## 窗口内冒烟二分

### 第一栏：阻断迁移

不过即立即切回旧代码并按上节真实回滚，窗口不得解除。

| # | 冒烟项 | 判据 | 为何阻断 |
|---|---|---|---|
| B1 | **各月分片都能读到** | `FileSummaryStore(root).get_all_summaries()` 条数 == 迁移前条数（**当次实测**）| 直接证伪迁移完整性 |
| B2 | **跨月查找正确** | 任取一条 2 月摘要 `get_summary_by_tweet(tweet_id)` 能取到且内容一致 | R1/R2 错 = 后续回存会造第二条 |
| B3 | **单片写回落对片** | 回存 1 条既有推文 → 该条仍在原月分片、**全分片中该 `tweet_id` 恰 1 条** | R2/R7 错 = 数据事故 |
| B4 | **读缓存不返回陈旧值** | 写后立即读，取到新值（`read_cache.load_summary_map()`）| S5 只做一半 = 4 读入口静默返回陈旧摘要 |

### 第二栏：不阻断迁移

不过时记录在案，恢复服务后按常规流程修复，不切回旧代码、不延长窗口。

| # | 冒烟项 | 所属工作线 | 为何不阻断 |
|---|---|---|---|
| N1 | 路径越界样本被拒 | Q11 路径护栏（S2）| 纯新增兜底断言，红了也不影响已迁移数据的正确性 |
| N2 | 临时文件带进程标识 | Q10（S3）| 命名格式问题，不改变落盘内容 |
| N3 | 坏行汇总告警恰 1 次 | Q9（S4）| 纯日志行为 |
| N4 | 纯读路径不触发全量索引重扫 | Q8 惰性索引（S6）| 性能项，退化 = 慢，不 = 错 |
| N5 | 新写入时间带时区 | Q3 时间口径（S9）| 只影响**此后**新写入，历史数据不受影响 |
| N6 | 议题 `last_updated_at` 取最晚 | Q5 议题聚合（S8）| 取值口径问题，可窗口外单独修 |

**二分的唯一判据**：**“这条红了，已迁移的摘要数据是否可能不正确 / 读不到？”** —— 是 → 第一栏；否 → 第二栏。

**禁止把第二栏任一条升入第一栏“以求稳妥”** —— 那等于取消本条加固、退回一刀切。若运维现场对某条归属存疑，**按第二栏处理并记录**（窗口内多停 1 分钟的代价，远小于 15 分钟拖成数小时）。

**Q4 导入拦截（S7）不在任一栏**：窗口内 REST 进程已关停，导入路径**不可达**，无从冒烟 → 归**窗口外**常规验证。

## 同一推文多条摘要自查 runbook

**什么时候跑**：① 每次迁移核对通过后跑一次（作为窗口内 B3 冒烟的补充全量版）② 此后**每周例行**跑一次 ③ 一旦有人报"某条推文的摘要在网页上打不开"**立即**跑。

**它查什么**：扫全部月分片，报出**任何出现 >1 次的 `tweet_id`** —— 这正是 § 2.1 残余竞态会制造、且 `get_summary_by_tweet:83` 会 `raise` 的那个状态。

**在哪跑**：纯标准库脚本，只认 `${XWATCHER_DATA_ROOT}`，**任意工作目录均可执行**，不需要仓库虚拟环境（须换解释器时设 `${XWATCHER_PYTHON}`）。本段代码块会被 `tests/summarization/test_chg042_monthly_shards.py` 逐字提取运行，且测试的工作目录并非仓库根——改动时不得引入 `cd`、相对路径解释器或其它 cwd 假设。

```bash
DATA_ROOT="${XWATCHER_DATA_ROOT:?请先设置 XWATCHER_DATA_ROOT}"
PYTHONPYCACHEPREFIX=$(mktemp -d) "${XWATCHER_PYTHON:-python3}" - "${DATA_ROOT}" <<'PY'
import sys, json, pathlib, collections
root = pathlib.Path(sys.argv[1])
shards = sorted((root / "summaries").glob("*.jsonl"))
if not shards:
    print("NG: 未找到任何月分片（数据根是否正确？迁移是否已执行？）"); sys.exit(2)
loc, total = collections.defaultdict(list), 0
for p in shards:
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line); total += 1
        loc[rec["tweet_id"]].append((p.name, rec["summary_id"], rec.get("created_at", "")))
dups = {k: v for k, v in loc.items() if len(v) > 1}
print(f"分片数={len(shards)} 记录数={total} 去重tweet_id={len(loc)}")
if not dups:
    print("OK: 未发现同一 tweet_id 的多条摘要"); sys.exit(0)
print(f"NG: {len(dups)} 个 tweet_id 有多条摘要 —— 这些推文的摘要页会报错")
for tid, rows in sorted(dups.items()):
    keep = max(rows, key=lambda r: r[2])          # 与 save_summary_record:62 同为字符串 max
    print(f"  tweet_id={tid}")
    for r in rows:
        print(f"    {'保留' if r is keep else '删除'} 分片={r[0]} summary_id={r[1]} created_at={r[2]}")
sys.exit(1)
PY
```

**退出码契约**：`0` = 干净 · `1` = 发现重复（输出已逐条标出保留/删除）· `2` = 分片缺失（环境问题，非数据问题）。

**修复动作**（`exit=1` 时）：① 按输出中标「删除」的 `(分片, summary_id)` 从对应 `.jsonl` 删除该行 ② **重启 MCP 与 REST 两个进程**（定位表不落盘，重启即弃掉陈旧表 —— 这是必需的一步，只删盘面不重启则进程内陈旧表仍在）③ 重跑本命令确认 `exit=0`。

⚠️ **保留判据必须是字符串 `max(created_at)`**，与 `save_summary_record:62`（§ 2.1 R2′）**同一口径**，禁按时间对象比较。

⚠️ **落稿自检**：本段脚本变量引用已全部用 `${VAR}` 花括号形式（`${XWATCHER_DATA_ROOT}` / `${DATA_ROOT}`），heredoc 用 `<<'PY'` 引号形式禁止外层展开；落盘后须跑 `bash -n` + 全角紧邻变量 grep 自检。

## 后续运维约定预留

后续新增约定时按“适用范围、风险、执行前置、具体命令、成功判据、失败/回滚、日志位置、责任人”结构追加；不得覆盖或弱化上面的停手窗口与跨进程互斥约束。
