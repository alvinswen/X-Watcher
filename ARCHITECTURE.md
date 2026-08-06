# X-Watcher 技术文档

> 采集自代码快照 `a3c67f7`（v1.51.2）· 2026-08-06
> 本文描述系统的**实际实现**，所有结论引用真实文件路径与行号。与代码冲突时以代码为准。

---

## 一、系统定位

X-Watcher 是一个面向 **AI Agent** 的 X（Twitter）平台信息监控服务。

它的定位有一个容易被误解的关键点：**X-Watcher 自身不含任何 LLM**。摘要、翻译、议题分类、综述撰写全部由调用它的 Agent 完成，X-Watcher 只负责抓取、存储、校验、溯源与状态管理。这是 v1.9.0 刻意坐实的架构决策（"数据层零 LLM"）。

因此系统有两类受众，优先级不同：

| 受众 | 入口 | 规模 |
|---|---|---|
| **AI Agent**（主） | MCP 协议，37 个工具 + 5 个资源 | 承载全部核心能力 |
| 内部运营 / PM（次） | Web 后台，10 个页面 | 查看与管理，不含智能环节 |

---

## 二、架构总览

### 2.1 技术栈

| 层 | 选型 | 版本 |
|---|---|---|
| 后端 | Python + FastAPI + Pydantic v2 | Python ≥3.12（CI 钉 3.12.13） |
| MCP | FastMCP（`mcp[cli]`） | ≥1.2.0 |
| 存储 | **文件层**（JSONL + JSON 文档 + 原子写） | 无数据库 |
| 前端 | Vue 3 + Element Plus + Pinia + Vite | Vue 3.5.27 / EP 2.13.2 / Vite 7.3.6 |
| 错误建模 | `returns.Result` | ≥0.23.0 |
| 指标 | prometheus-client | ≥0.19.0 |

> **无数据库**是重要事实：项目早期用过 PostgreSQL + SQLAlchemy，在 v1.14.0–v1.18.0 的四包专项中永久下线并删除全部实现（PM 明确裁决"数据库方案永不回归"）。当前所有持久化都落在文件系统。

### 2.2 包结构与体量

`src/` 下 17 个业务包，按代码量排序：

| 包 | 文件 | 行数 | 职责 |
|---|---|---|---|
| `scraper/` | 27 | 4827 | TwitterAPI.io 客户端、解析、校验、抓取编排、增量分组、任务注册表 |
| `mcp/` | 18 | 3281 | FastMCP server、7 组 tools、2 组 resources、鉴权与 Action Guard |
| `subjects/` | 18 | 2708 | 议题 CRUD、match/digest/review/feedback/eval、溯源 |
| `preference/` | 15 | 1551 | 关注账号、X 档案、抓取配置 |
| `api/` | 9 | 1480 | admin / tweets / status / config / sync 路由 |
| `user/` | 16 | 1077 | 用户、JWT、API Key、登录限流 |
| `source_candidates/` | 10 | 1061 | 信源候选挖掘/试读/预审/终审 |
| `summarization/` | 12 | 784 | 摘要读写、月分片存储、译文校验门 |
| `sync/` | 12 | 756 | 导入导出 |
| `cli/` | 5 | 565 | click CLI |
| `browse/` | 8 | 462 | 按日期/作者浏览 |
| `storage/` | 7 | 428 | 原子写、JSONL/JSON 引擎、路径规则、视图、索引 |
| `data_layer/` | 4 | 640 | Provider 工厂 + 仓储契约 |
| `shared/` | 8 | 290 | 审计日志、读缓存、连通性检查、错误文案 |
| `search/` `feed/` `monitoring/` | 9/9/4 | 264/253/179 | 搜索、Feed、指标 |

包内典型分层：`api/`（路由 + schemas）→ `services/`（编排）→ `infrastructure/`（`File*Store`）+ `domain/`（Pydantic 模型）。`subjects/` 是例外，用扁平的 `store.py` / `models.py` / `protocol.py` + `services/`。

### 2.3 依赖方向

```
storage/          ← 零依赖底座（不 import 任何业务包）
   ↑
data_layer/       ← Provider 工厂（反向依赖全部业务包，但运行时零耦合，见 3.1）
   ↑
各业务域 ────────→ 横向依赖真实存在，非纯洋葱：
                    scraper → summarization
                    source_candidates → subjects
                    shared → scraper / summarization
   ↑
api/ mcp/ cli/    ← 接口层
```

`storage/` 是唯一的零依赖底座——`src/storage/*.py` 不 import 任何业务包。

---

## 三、数据层

### 3.1 Provider 工厂

唯一文件 `src/data_layer/provider.py`（328 行），提供 **20 个 `get_*_repo()` 工厂**，全部固定返回 `File*` 实现（无分支、无注册表、无 DI 容器）。

两个关键设计：

**惰性 import**：所有实现类的 import 写在函数体内（`provider.py:54,64,74,84…`），返回类型 import 放在 `if TYPE_CHECKING:` 块内（`:14-34`）。docstring 明写理由——"import 延迟到函数内，使 env 变更逐调用生效（测试可 monkeypatch）"（`:4`）。这让 `data_layer` 名义上依赖全部业务包，运行时却零耦合。

**数据根单一真值源**：`_data_root()`（`:37-38`）读 `os.environ.get("XWATCHER_DATA_ROOT", "data_migrated")`。这是**全项目唯一直接读该环境变量的地方**，且刻意不走 `Settings`。

两个 async→sync 桥适配器是 PG 下线的遗留：`_FileExportSyncAdapter`（`:155-190`，用 `asyncio.run` 桥接）与 `_FileImportSyncAdapter`（`:193-250`，额外用 `copytree` 到临时目录实现 dry-run 隔离）。

### 3.2 仓储契约与防漂移闸

`src/data_layer/repositories.py`（295 行）定义 **14 个 Protocol 契约**。

契约的编写原则值得注意：**按实测真正被调用到的成员编写，不是实现类的全量镜像**（`repositories.py:8`）。文件头有完整的"如何加宽本契约"施工手册（`:6-21`），并明令**禁止用 `# type: ignore` 绕过**。

**17 道静态实现断言**（`:242-295`）形如：

```python
def _assert_0(s: FileTweetStore) -> TweetStore: return s
```

整块在 `if TYPE_CHECKING:` 内——编译期由 mypy 真验结构实现，运行时零开销、不进字节码。任一签名漂移（含 keyword-only `*` 与默认值差异）门禁即红。

同类闸在议题域也有一道：`SubjectRepoProtocol`（`src/subjects/protocol.py:32-177`）+ `_assert_file_subject_store_implements`（`:195-200`）。

> ⚠️ 已知文档漂移：`protocol.py:4` 的 docstring 自称"32 成员"，实测 `async def` 计数为 **34**（`get_tweet_cards_by_ids`、`get_tweet_author_ids` 后加入未同步计数）。

### 3.3 存储引擎

`src/storage/` 四个引擎文件，职责严格分离：

| 文件 | 关键 API | 说明 |
|---|---|---|
| `atomic.py` | `atomic_replace(path, data)`（`:33-41`） | **全项目唯一的落盘写原语**：临时文件 → write → flush → `os.fsync` → `os.replace` |
| | `shard_lock(path)`（`:13-30`） | 进程内 `asyncio.Lock`，存于 `WeakValueDictionary` 防内存无界增长 |
| `jsonl_store.py` | `read_shard` / `write_shard` / `append` / `upsert` | `read_shard` 遇坏行跳过并计 warning（`:25-33`） |
| `doc_store.py` | `read_doc` / `atomic_write_doc` | 单 JSON 文档，`indent=2, ensure_ascii=False` |
| `index.py` | `TweetIdIndex`（`:11-32`） | 内存 `set[str]`，启动时全量扫描构建 |
| `views.py` | `by_day_upsert` / `rebuild_by_day` / `reconcile_by_day` | 派生视图维护 |

**权威源与派生视图分离**是核心契约：权威源是 `tweets/<author>/<YYYY-MM>.jsonl`，派生是 `_views/by-day/<YYYY-MM-DD>.jsonl`，**派生永不作为裁决依据**（标记 T-VIEW-001，`views.py:4`）。`reconcile_by_day`（`:79-103`）做集合 + 内容 + 归档日三重对账。

> 运维推论（`OPERATIONS.md:92-94`）：因为原子写在最终文件上不持有句柄，`lsof` 对活跃写入的检出率为 **0**。所以"数据文件无进程持有句柄"不能单独作为"已停写"的判据。

### 3.4 物理布局

唯一路径规则源 `src/storage/paths.py`（171 行），每条路径都过 `_guard()` 越界检查（`:10-15`，`is_relative_to(root)` 否则抛"路径越界"）。

| 数据 | 路径 | 分片规则 |
|---|---|---|
| **推文（权威）** | `tweets/<author>/<YYYY-MM>.jsonl` | 作者 × UTC 月**双维**分片 |
| by-day 视图（派生） | `_views/by-day/<YYYY-MM-DD>.jsonl` | UTC 日 |
| **摘要** | `summaries/<YYYY-MM>.jsonl` | 按 `created_at` UTC 月 |
| 议题主档 / 索引 | `subjects/<sid>.json` / `subjects/index.json` | 单文档 |
| 议题命中 | `subjects/<sid>/matches/<YYYY-MM>.jsonl` | 按 `matched_at` 月 |
| 议题摘报 | `subjects/<sid>/digests/<YYYY-MM>.jsonl` | 按 `interval_start` 月 |
| 议题综述 | `review/latest.json` + `review/history/<version>.json` | 单文档 + 版本 |
| 议题溯源 | `subjects/<sid>/provenance/<kind>/<key>.json` | kind ∈ {matches, digests, review}，硬校验 |
| 信源候选 | `source_candidates/<candidate_id>.json` + `index.json` | 单文档 |
| 增量抓取进度 | `scrape_state/groups.json` | 单文档 |
| 关注 / 档案 / 用户 / 统计 | `follows/follows.json` 等 | 单集合文档 |

**摘要月分片**是 v1.39.0 的一次性生产迁移（52,567 条 / 51 MB，跨片定位从 550.6 ms/条降到 54.8 ms/条）。相关机制：

- `_ready_summary_shards()`（`file_summary_repository.py:41-56`）：若无月分片但遗留 `summaries.json` 非空 → **抛错 fail-loud**，防静默丢数据
- 进程内定位表缓存，签名 = 各分片的 `(相对路径, st_mtime_ns, st_size)` 排序元组
- 跨月搬迁：目标分片 ≠ 旧分片时先删旧片记录再写新片

---

## 四、抓取管线

### 4.1 两条互斥路径

由 `settings.scraper_incremental_enabled` 在 `ScrapingService.scrape_users` 顶部分叉（`src/scraper/scraping_service.py:118-144`）。

#### 路径 A：常规逐账号抓取（默认）

```
REST POST /api/admin/scrape  或  MCP trigger_scrape
  → ScrapingService.scrape_users(usernames, limit, task_id, manual_limits)
      ├─ TaskRegistry 建任务、置 RUNNING
      ├─ resolve_manual_limits()        ← 服务层单点解析，REST/MCP 共享（v1.28.0）
      ├─ asyncio.Semaphore(3) 并发
      └─ 逐账号 scrape_single_user
           ├─ 模块级并发防护（_scraping_usernames set + threading.Lock）
           ├─ limit 计算（manual 优先，否则 LimitCalculator 动态算）
           ├─ 页预算 budget = ceil(limit/20)，max_pages = min(budget, page_cap)
           └─ for page in range(max_pages):
                ├─ TwitterClient.fetch_user_tweets(username, cursor)
                ├─ 404 且首页且未重试过 → detect_and_fix_rename（改名自愈）
                ├─ TweetParser.parse → TweetValidator.validate_and_clean_batch
                ├─ 截断到 remaining，超出计入 discarded_by_limit
                ├─ FileTweetStore.save_tweets（含 early-stop）
                └─ ArticleFetchService.fetch_and_save_articles
           └─ 判停顺序是契约：limit → 游标 → 跳过率>0.8 → 空页 → 页数边界
```

落库终点 `FileTweetStore.save_tweets`（`file_tweet_repository.py:56-102`）的关键语义：**"canonical 写成功 = 提交点"**，随后才增量更新 by-day 派生视图。early-stop 在连续已存在数 ≥ 阈值时把剩余全部计入 skipped 并 break。

#### 路径 B：按组增量搜索（v1.51.0 新增）

`IncrementalScrapeService.run_round()`（`src/scraper/services/incremental_scrape_service.py:85-170`）把账号分组，用 X 的 search 接口配合 `since_id` 做增量拉取，显著降低 API 花费。

分组与查询构造在 `group_planner.py`（纯函数）：

- 查询白名单正则（`:10-14`）：`^\(from:X( OR from:Y)*\) include:nativeretweets( since_id:\d+)?$`
- `assert_query_safe`（`:18-37`）**在 IO 前 fail-fast**：非空、无重复、账号数与串长不超限、结构必须完全匹配白名单
- `plan_initial_groups` 用哨兵 `since_id = "9999999999999999999"` 预留未来增长空间
- `apply_membership_changes` **只删不动老成员**，新成员优先追加末组

**水位推进语义**（增量正确性的核心）：`_advance_or_hold`（`:291-336`）只有在 **IO 完整且存在早于 `now - overlap_minutes` 的推文**时才推进 `since_id`。撞页数闸则存 `resume_cursor` 续翻。

四种告警：`sentinel_misconfigured`、`progress_stalled`、`backlog_drain_slow`、`suspected_query_failure`（哨兵账号整轮 0 命中时触发）。

### 4.2 客户端重试与熔断

`src/scraper/client.py` 类常量（`:369-376`）：

```python
DEFAULT_MAX_RETRIES = 5
DEFAULT_BASE_DELAY  = 1.0    # 指数退避基数
DEFAULT_MAX_DELAY   = 60.0   # 退避封顶，无 jitter
DEFAULT_TIMEOUT     = 30.0
NON_RETRYABLE_STATUS_CODES = {401, 403, 404, 422}
```

统一重试内核 `_request_with_retry`（`:429-494`）：不可重试状态码立即返回 `Failure`；超时与网络错误走同一退避。

**熔断器**（`circuit_breaker.py`）是进程级单例，`failure_threshold=5`、`recovery_timeout=60s`，三态 `CLOSED → OPEN → HALF_OPEN`。关键细节：只有 `_fetch_with_retry` 接熔断器，且**不可重试类错误不计入失败**（`client.py:803-804`）——401/404 是调用方问题，不该熔断整个上游。

> v1.36.0 修复过一个真实的 flaky 根因：熔断器作为进程级单例在测试间泄漏状态，改为 autouse fixture 保存/还原。

### 4.3 limit 契约

三个层级，优先级明确（v1.37.0 才让 limit **第一次真实生效**）：

1. **手动 limit**（最高）：`follows` 记录的 `manual_limit`，由 `resolve_manual_limits` 单点解析，不受传入上限约束
2. **动态 limit**：`LimitCalculator.calculate_next_limit`（`limit_calculator.py:43-103`）四条策略——无历史用默认；满抓取则翻倍封顶；连续空抓 ≥3 次降到最小；正常情况按 EMA 新增率反推 × 1.2 安全边际
3. **传入上限**：`actual_limit = min(dynamic_limit, limit)`

页数闸：`budget_pages = ceil(actual_limit / 20)`，`max_pages = min(budget_pages, page_cap)`。

> ⚠️ 两个页数配置**语义不同，禁止互用**（`config.py:130-138` 有明确注释）：`scraper_max_pages_per_scrape` 是**每账号每次**，`scraper_incremental_max_pages_per_round` 是**每组每轮**。

---

## 五、摘要与议题域

### 五.1 三种"摘要"不要混淆

> 历史术语提示：项目 PM 侧文档曾用 `TopicSummary` 一词，**该类型在当前代码中已不存在**（随 v1.2.0 下线 M05 主题聚合而消失）。

| | `SummaryRecord` | `SubjectDigest` | `SubjectReview` |
|---|---|---|---|
| 定义 | `summarization/domain/models.py:11-37` | `subjects/models.py:44-54` | `subjects/models.py:68-78` |
| 粒度 | **单条推文** | **议题 × 时间区间** | **议题全量（带版本）** |
| 定位 | 中文摘要 + 翻译 | L1 滚动新闻 | L2 活综述 |
| 主键 | `summary_id`(UUID) | `(subject_id, interval_start, interval_end)` | `(subject_id, version)` |
| 并发控制 | 定位表 + 分片锁 | 分片锁 append | **乐观锁**（`prev_version` 不符抛 `ReviewConflictError`） |

**译文校验门**（`summarization/domain/summary_verification.py`）：`save_summaries` 写库前逐条校验，未过项不入库而计入 errors。长度比基准是剥 URL 后的正文字符数，比例区间 `[0.25, 1.50]`（注释解释了为何不用 slash-command 字面的 60%–120%——那会误杀几乎所有合法翻译）。

### 5.2 议题的真实机制

`Subject` 模型（`subjects/models.py:17-27`）有 `nl_description`（自然语言描述）与 `keywords` 字段，但**这两个字段在后端不参与任何自动匹配计算**——全域没有查询执行器。

真实流程：

```
create_subject（置 pending_classify=True）
  → 外部 Agent 通过 MCP get_pending_jobs 取待办
  → Agent 读 nl_description 自行判定
  → 调 put_subject_matches 回写 tweet_id
  → SubjectClassifier.write_matches 校验引用不悬空 → upsert → 关闭 pending
```

**分类智能完全在调用方**。活跃议题上限 20（`subjects/constants.py:8`）。

### 5.3 双时间轴

全域一致的契约：

| 轴 | 语义 | 实现 |
|---|---|---|
| `ingest` | 按 `matched_at`（入库/分类时间）圈窗 | 默认 |
| `publish` | 按推文 `created_at`（发布时间）圈窗 | `publish_window_matches`（`store.py:522-558`），无发布时间的落入 `skipped_no_publish_time_ids` |
| `review` | 全量，忽略区间 | — |

### 5.4 溯源指纹对账

`src/subjects/provenance.py` 定义 4 个必填字段：`playbook_id`、`playbook_version`、`prompt_hash`、`candidate_set_hash`。后两者必须是 64 位小写 sha256。

**服务端按同一口径重算候选集 hash，不符即拒收**（`:69-71`），错误消息带完整诊断（系统条数/hash 前 8 位/示例 id vs 技能传入的对应值）。

这就是为什么 MCP 提供 `get_subject_candidate_set` 作为权威候选圈定入口——用 `get_subject_feed` 的 id 自算 hash 会因分页（≤500）与边界口径差异被拒收。

### 5.5 三条评审线（不要混淆）

| 线 | 类型 | 关键点 |
|---|---|---|
| **议题综述** | `SubjectReview` | 乐观锁版本流转；`cited_tweet_ids` 必须 ⊆ 该议题命中集；双写 `latest.json` + `history/<v>.json` |
| **反馈裁决** | `SubjectFeedback` | `authority` 分 `human_correction` / `agent_selfeval`——**人机权威分离**；`who` 强制 `^(human\|agent):.+$`；支持 `supersedes` 覆盖链 |
| **评估账本** | `SubjectEval` | `tier` 三档 `hygiene` / `judge` / `human`；卫生体检只支持 digest/review，match 走人工更正率 |

### 5.6 术语歧义警告

项目里 "candidate" 有两个完全不同的含义，文档与代码都需注意：

- **`candidate_set` / `candidate_ids`**（议题域）= 某议题在某口径下的**推文 ID 全集**，用于溯源指纹
- **`SourceCandidate`**（信源域）= **待评估的信源账号**，即"要不要关注这个 X 用户"

---

## 六、接口层

### 6.1 MCP（37 个工具 + 5 个资源）

详见《MCP 工具参考手册》。要点：

- 工具总数 **37**，由 golden 快照 `tests/mcp/golden/mcp_tool_schemas.json` 逐字节冻结，双重守卫用例校验
- 快照冻结四件：`description` / `parameters` / `signature` / `docstring`
- 再生成：`XWATCHER_REGEN_MCP_GOLDEN=1` 跑对应测试
- 快照测试内置 **LEAK-GUARD**（`test_mcp_schema_snapshot.py:13-17`）：断言导入的 `src` 包位于当前仓，防止误测已安装的 wheel

### 6.2 REST（56 条路由）

装配入口 `src/main.py:172-234`，17 个挂载点。路由分布：`subjects` 12、`preference` 9、`user` 10、`api/routes` 13、`browse` 4、`source_candidates` 3，其余各域 1–2 条，另有 `/health`（`main.py`）与 `/metrics`（`monitoring/`）。

`GET /health`（`main.py:133-169`）：检查 data_root 存在性，**始终返回 200** 以兼容 Docker HEALTHCHECK，body 含 `status` / `components` / `version` / `commit`（commit 由 `git rev-parse --short HEAD` 取，timeout 1 秒，失败返回 `"unknown"`）。

中间件顺序有严格要求（`pyproject.toml` 为 `src/main.py` 单独豁免 E402，注明"启动时序 import 刻意设计"）：CORS → 全局异常处理器 → PrometheusMiddleware → 路由 → **SPAMiddleware 必须最后**。

### 6.3 鉴权四层

| 层 | 机制 | 位置 |
|---|---|---|
| **1. 双通道认证** | API Key（`X-API-Key`）**优先于** JWT Bearer；API Key 未命中直接 401，**不降级到 JWT** | `user/api/auth.py:27-98` |
| **2. Scope** | 普通用户仅 `["user"]`；管理员 `["admin","user","subjects:write"]` | `mcp/token_verifier.py:25-79` |
| **3. `require_admin()`** | 管理类、摘要类、终审类工具/路由 | 各 tools/routes |
| **4. Action Guard** | 环境变量事前拦截 4 个高危工具 + 抓取总开关 | `mcp/security.py` |

API Key 格式 `sna_` + `token_hex(16)`，**存哈希不存明文**（SHA-256）。JWT 默认 24 小时。

**登录限流**（`user/services/login_rate_limiter.py`）有个容易踩的语义：连续失败 5 次锁 900 秒，但粒度是**全实例单闸**——不是按 IP、不是按账号。锁定期内**任何**登录请求（包括密码正确的）一律拒。内存态，进程重启清零。

**JWT 密钥启动期硬校验**（`config.py:198-240`）：不得为默认值 `"change-me-in-production"`、不得空白、长度 ≥32。不合规直接 `sys.exit(1)` 并打印生成命令。REST 与 MCP 两个入口都调。

---

## 七、配置

`src/config.py`（249 行）Pydantic `BaseSettings`，无 `env_prefix`（环境变量名 = 字段名大写），`extra="ignore"`。

关键配置项（完整表见代码）：

| 字段 | 默认 | 约束 |
|---|---|---|
| `twitter_api_key` | **必填** | — |
| `scraper_limit` | 30 | 1–1000 |
| `jwt_secret_key` | `change-me-in-production` | 启动期强度校验 |
| `jwt_expire_hours` | 24 | — |
| `scraper_max_pages_per_scrape` | 10 | 1–50（**每账号**） |
| `scraper_incremental_enabled` | `False` | — |
| `scraper_incremental_max_pages_per_round` | 25 | 1–100（**每组每轮**） |
| `scraper_incremental_overlap_minutes` | 30 | 0–1440 |
| `scraper_incremental_sentinels` | `GaryMarcus,levelsio,elonmusk` | 逗号分隔 |
| `feed_max_tweets` | 200 | 1–1000 |
| `twitter_balance_warning_threshold` | 50000 | 约 12 天用量 |

**不走 Settings 的环境变量**（旁路读取）：

| 变量 | 默认 | 位置 |
|---|---|---|
| `XWATCHER_DATA_ROOT` | `data_migrated` | `data_layer/provider.py:38` |
| `MCP_SCRAPE_ENABLED` | `true` | `mcp/security.py:76` |
| `MCP_*_ALLOWED_ACTIONS`（4 个） | 未设=全允许 | `mcp/security.py:21-24` |

> `.env.example` 未列出 `LOG_FORMAT` / `LOG_FILE*` / `CLAUDE_CODE_MODEL_NAME` / `SCRAPER_MIN_LIMIT` / `SCRAPER_MAX_LIMIT` / `SCRAPER_EMA_ALPHA` / `SCRAPER_EARLY_STOP_THRESHOLD` / `TASK_MAX_RUNNING_SECONDS` 共 8 项，需要调这些时得查 `config.py`。

---

## 八、质量门禁体系

这是项目在 41 天内积累的重要资产，值得单独说明。

### 8.1 六道 CI 门禁

`.github/workflows/ci.yml`，触发 `pull_request` + `push: main`，**版本四钉**（`uv 0.11.13` / `Python 3.12.13` / `Node 22.23.1` / `ubuntu-24.04`）：

| # | job | 命令 | 门禁语义 |
|---|---|---|---|
| 1 | `backend-lint` | `scripts/check-lint.sh` | 全仓 ruff = 0 债 |
| 2 | `backend-types` | `scripts/check-types.sh` | 全仓 mypy strict = 0 债 |
| 3 | `backend-pytest` | `pytest -q --cov` | 1045 用例全过 + 覆盖率 ≥85% |
| 4 | `web-build` | `npm run build` | `vue-tsc -b` 类型门 + 构建 |
| 5 | `web-vitest` | `npx vitest run` | 前端约 120 用例 |
| 6 | `web-lint` | `npm run lint` | 前端 eslint 正确性档 = 0 error |

> ⚠️ `OPERATIONS.md:319` 仍写"5 个 required-check"，**已滞后**——第 6 个 `web-lint` 恰恰是该文档自己那一节引入的。

依赖安装一律 fail-closed：`uv sync --locked`（锁与声明不一致即拒装）。`uv.lock` 锁定 **64 个包**。

另有 `security-audit.yml`：PR + 每周一 + 手动触发。红灯口径不对称——后端生产依赖**任意**已知漏洞即红；前端生产依赖 high+critical **合计 >0** 才红。

### 8.2 门禁脚本的五态设计

`scripts/check-lint.sh` 的退出码语义值得借鉴：

| 码 | 含义 |
|---|---|
| 0 | 通过，全仓 0 lint 债 |
| 1 | 有债，提示 `ruff check . --fix` |
| 2 | ruff 未安装，给 pip / uv 双口径指引 |
| **3** | **版本断言拒跑** |
| ≥2 | 透传 ruff 自身崩溃码 |

第 3 态是防御要点：脚本从 `pyproject.toml` grep 出 `ruff==X.Y.Z` 作为**唯一事实源**，与实际版本比对，不匹配即拒跑——防止在无 CI 环境下工具版本漂移导致门禁语义悄悄改变。

`check-types.sh` 是四态（无版本断言，因为 mypy 用 `>=1.7.0` 未钉死）。

### 8.3 类型债治理成果

v1.11.0–v1.24.0 的 14 包专项用"棘轮"方式把 mypy 存量债从 **604 条清到 0**，最后一包撤除 `mypy-baseline` 记账机制，门禁语义变为"通过 = 全仓 0 类型债"。

当前维护方式：`scripts/check-types.sh` 或裸跑 `mypy src`。

### 8.4 测试基座契约

`tests/conftest.py` 在**模块导入期**就 `mkdtemp` 并钉 `XWATCHER_DATA_ROOT`（`:5-9,22-28`），"堵死未显式设 data_root 的测试误读写生产数据目录的全部路径"。`load_dotenv()` 后再钉一次做双保险，注释写着"测试套件必须 env-无关"。还做了日志隔离，停掉 `QueueListener` 防止写生产日志。

`filterwarnings = ["error", ...]` —— **warning 即错误**，仅精确豁免 1 条 starlette/httpx 弃用告警。

---

## 九、关键设计决策

以下决策都有代码注释背书，是理解本系统的要点：

1. **零 LLM** — 系统不含任何模型调用。智能环节全部外包给调用方 Agent，服务端只做存储、校验、溯源。这让系统可测试、可审计、成本可控。

2. **单一写原语** — 所有落盘都经 `atomic_replace`（tmp + fsync + `os.replace`）。副作用是 `lsof` 无法检出活跃写入，运维判据需据此调整。

3. **权威源 / 派生视图分离** — 派生视图可一键重建，永不作为裁决依据（T-VIEW-001）。

4. **契约按实测调用面裁剪** — 不做实现类的全量镜像，配静态断言防漂移，运行时零开销，禁止 `# type: ignore` 绕过。

5. **Result 类型贯穿抓取链路** — `returns.Result[T, TwitterClientError]` + `match/case` 结构化匹配，错误是值不是异常。

6. **fail-loud 与 fail-soft 边界清晰**：
   - fail-loud（直接崩）：JWT 弱密钥 → `sys.exit(1)`；未迁移的摘要数据 → `RepositoryError`；查询串越白名单 → IO 前 `ValueError`
   - fail-soft（只告警）：统计更新失败、profile 同步失败、backfill 状态更新失败

7. **溯源指纹强制对账** — 服务端重算 hash 拒收不符的写入，让 Agent 产物可追溯、可复核。

8. **fail-closed 的摘要回写三闸** — 类型 → 存在性 → 译文校验。这是 v1.43.0 针对一次真实的"调用方转写幻觉"事件加的防御（当时 Agent 报告 11 个损坏 ID，核实全库 54,313 条中 0 条非数字 ID）。

---

## 十、已知技术债

代码与工程层面的已知不足，如实记录供后续规划。

| # | 项 | 现状 |
|---|---|---|
| 1 | 前端测试盲区 | 7 个页面零组件测试（含三个最大业务页），无 E2E |
| 2 | 前端风格 lint 缺位 | eslint 只开正确性档，454 条风格项留给未启动的 prettier 专项 |
| 3 | `get_audit_log` 名不副实 | 恒返回空，5 个参数全不生效；真实审计写在 `LOG_FILE` |
| 4 | `SubjectRepoProtocol` 计数漂移 | `protocol.py:4` docstring 自称 32 成员，实测 34 |
| 5 | 前端字体依赖公网 CDN | `style.css` 从 jsDelivr / Google Fonts 拉取，断网即回退到系统字体（不影响功能） |
| 6 | 日志轮转未验证 | 配置有 `log_file_max_bytes` / `log_file_backup_count`，但未见轮转实际生效的记录 |

### 已闭合

| 项 | 闭合于 |
|---|---|
| ~~版本号多源且停在 `0.1.0`~~ | **v1.51.1**（4 源 + 1 测试断言归一到 `pyproject.toml`）+ **v1.51.2**（补位对齐基线编号） |
| ~~`cryptography` 已知漏洞 `PYSEC-2026-3552`~~ | **v1.51.2**（升级至 `50.0.0`） |
| ~~README / OPERATIONS 文档漂移~~ | 本轮里程碑文档梳理（README 修正 11 处事实错误） |

> 部署与运维层面的注意事项（备份策略、日志留存、监控告警等）取决于各自的部署形态，见 [OPERATIONS.md](OPERATIONS.md)。
