# Changelog

X-Watcher 的全部版本变更记录。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## 版本号约定

本项目的版本有两套编号，一一对应：

- **git tag `vX.Y.Z`** —— 仓库内的正式版本标记，也是 GitHub Release 的锚点。
- **基线编号 `BX.Y.Z`** —— 产品管理侧账本（`x-watcher-pm` 运营仓）中的同一版本，`B` 是 baseline 前缀。

两者数字部分完全相同，例如 git tag `v1.51.0` ⟺ 基线 `B1.51.0`。每个版本都对应 main 分支上一个确定的 commit，可用 `git show v1.51.0` 查看。

版本递进遵循这套项目内规则：新增用户可见能力递增 minor（`1.50.0` → `1.51.0`），缺陷修复与不改变对外行为的内部治理递增 patch（`1.24.0` → `1.24.1`）。

## 里程碑总览

截至 `v1.51.2`，项目在 43 天内完成 60 个版本、63 个交付包、71 个已合并 PR。

| 阶段 | 版本区间 | 时间 | 版本数 | 主线 |
|---|---|---|---|---|
| 项目接入与精简 | `v1.0.0` – `v1.2.3` | 06-24 ~ 06-27 | 6 | 建立首个基线，下线调度与主题聚合两个模块，配置收口到 file 模式 |
| Subject 议题体系 | `v1.3.0` – `v1.6.0` | 06-27 ~ 06-30 | 6 | 引入 continuous-query 语义的议题订阅，两层综述，架构掉头为 skill 驱动 |
| L4 Self-Harness 自证 | `v1.7.0` – `v1.9.0` | 07-02 ~ 07-04 | 3 | 溯源与反馈两层地基、评估门闭环，剥离残留 LLM 坐实数据层零 LLM |
| 安全加固 | `v1.10.0` | 07-04 | 1 | MCP 读工具提示词注入防御，Action Guard 扩容 |
| 工程债治理 | `v1.11.0` – `v1.24.1` | 07-05 ~ 07-12 | 15 | mypy 棘轮式清偿 604 条存量类型债至 0，database/SQLAlchemy 全域退役 |
| 重构专项 R1–R8 | `v1.25.0` – `v1.35.0` | 07-13 ~ 07-20 | 11 | 脚手架清除、性能止血、MCP 契约冻结、god-file 拆分、前端重构、错误处理统一 |
| 稳固与加固 R9 | `v1.36.0` – `v1.43.0` | 07-20 ~ 07-26 | 8 | 测试隔离、limit 契约修真、安全暴露面收窄、存储层分片迁移、分层收尾 |
| 工程护栏 | `v1.44.0` – `v1.45.0` | 07-30 ~ 07-31 | 2 | CI 自动门禁 5 job + 依赖锁定 + 分支保护，前端 lint 门禁 |
| 综述阅读体验 | `v1.46.0` – `v1.47.0` | 08-02 | 2 | 引用面板去复读与推文原文卡，综述历史版本回看 |
| 信源发现 | `v1.48.0` – `v1.51.0` | 08-03 ~ 08-04 | 4 | 信源候选域与挖掘/评审 MCP 工具、预审 skill、评审队列页、增量搜索抓取 |
| 版本号治理与安全 | `v1.51.1` – `v1.51.2` | 08-06 | 2 | 版本号收敛为单一事实源；cryptography 安全升级 |

---

## 版本号治理与安全 hotfix（v1.51.1 – v1.51.2）

### [v1.51.2] · 2026-08-06

安全 hotfix：`cryptography 49.0.0 → 50.0.0` 消除 `PYSEC-2026-3552`，并把版本号补位到 `1.51.2`

`a3c67f7` · `CHG-056` · [PR #75](https://github.com/alvinswen/X-Watcher/pull/75)

> 恰 2 文件、0 行源码。`cryptography` 是 `pyjwt` 的传递依赖（鉴权链路上的加密库），故走升级而非豁免。定向升级后包总数仍 64，无第三方漂移。**自此代码自报版本与基线编号完全对齐。**

### [v1.51.1] · 2026-08-06

版本号单一事实源收敛：4 个独立硬编码源 + 1 处测试断言归一到 `pyproject.toml`

`570078c` · `CHG-055` · [PR #74](https://github.com/alvinswen/X-Watcher/pull/74)

> 项目此前跑了 58 个版本，而 `/health`、OpenAPI `info.version`、`x-watcher --version` 一直自报 `0.1.0`。本版把版本号收敛为单一事实源，并将 `/health` 的版本测试改为契约式断言（对未来发版免疫）。

## 信源发现与增量抓取（v1.48.0 – v1.51.0）

### [v1.51.0] · 2026-08-04

增量搜索抓取（incremental-search-scraping）

`f8dee9c` · `CHG-054` · [PR #73](https://github.com/alvinswen/X-Watcher/pull/73)

### [v1.50.0] · 2026-08-03

信源评审队列页 + 候选域 REST（candidate-review-ui）

`f9d5969` · `CHG-053` · [PR #72](https://github.com/alvinswen/X-Watcher/pull/72)

### [v1.49.0] · 2026-08-03

source-review 预审 skill（source-review-skill）

`16c38b3` · `CHG-052` · [PR #71](https://github.com/alvinswen/X-Watcher/pull/71)

### [v1.48.0] · 2026-08-03

信源候选域 + 挖掘/评审 MCP 工具（source-candidate-domain）

`3c5c4bb` · `CHG-051` · [PR #70](https://github.com/alvinswen/X-Watcher/pull/70)

## 综述阅读体验（v1.46.0 – v1.47.0）

### [v1.47.0] · 2026-08-02

综述历史版本回看（review-history-viewer）

`b479116` · `CHG-050` · [PR #69](https://github.com/alvinswen/X-Watcher/pull/69)

### [v1.46.0] · 2026-08-02

综述引用面板去复读 · 推文原文卡（review-cite-tweet-cards）

`19bdab5` · `CHG-049` · [PR #68](https://github.com/alvinswen/X-Watcher/pull/68)

## 工程护栏：CI 门禁与依赖锁定（v1.44.0 – v1.45.0）

### [v1.45.0] · 2026-07-31

工程护栏二期：前端 lint 门禁 + CI 挂件三件（web-lint-ci-hardening）

`39aeba7` · `CHG-048` · [PR #65](https://github.com/alvinswen/X-Watcher/pull/65)

### [v1.44.0] · 2026-07-30

工程护栏：CI 自动门禁 + 依赖锁定（ci-dependency-guardrails）

`4aa9837` · `CHG-047` · [PR #63](https://github.com/alvinswen/X-Watcher/pull/63)

## 稳固与加固期 · R9 专项六包（v1.36.0 – v1.43.0）

### [v1.43.0] · 2026-07-26

save_summaries tweet_id 边界防御（harden-summary-id-boundary）

`aa88a72` · `CHG-046` · [PR #62](https://github.com/alvinswen/X-Watcher/pull/62)

### [v1.42.0] · 2026-07-25

分层收尾终局包（layering-closeout · 重构专项 R9f · R9 六包收官）

`7268d0f` · `CHG-045` · [PR #61](https://github.com/alvinswen/X-Watcher/pull/61)

### [v1.41.0] · 2026-07-23

议题管理页样式作用域收敛 + 受控视觉变更（web-scoped-hardening · 重构专项 R9e · 前端包）

`8280445` · `CHG-044` · [PR #60](https://github.com/alvinswen/X-Watcher/pull/60)

### [v1.40.0] · 2026-07-22

数据层 Provider 契约门面（provider-protocol-facade · 非专项 · 2026-07-22 债务盘点两条结构性债之一）

`f52a86a` · `CHG-043` · [PR #59](https://github.com/alvinswen/X-Watcher/pull/59)

### [v1.39.0] · 2026-07-21

存储层加固（R9 专项第 4 包 · R9d · 本轮最大包 · 含一次性生产数据迁移）

`99a5b5c` · `CHG-042` · [PR #57](https://github.com/alvinswen/X-Watcher/pull/57)

### [v1.38.0] · 2026-07-21

安全暴露面加固（R9 专项第 3 包）：路径穿越白名单双入口（sync 导入服务层三入口同源收口 + 抓取解析器守卫 · 严格版规则只拦不改 · 逐条跳过不连坐 + 拦截统计显式回显）+ 明文密钥比较 3 处改 secrets.compare_digest（双侧 bytes 化 · 消除时序侧信道 + 堵非 ASCII 401→500 崩溃面）+ 服务监听默认 5 处 0.0.0.0→127.0.0.1（含 MCP SSE · LAN 需显式放开 + README 迁移说明）+ 登录失败限流（连续 5 次锁 900s · 全实例单闸 · 429+文案+Retry-After · 内存态重启清零 · 零新增依赖）

`b0f69a3` · `CHG-041` · [PR #56](https://github.com/alvinswen/X-Watcher/pull/56)

### [v1.37.0] · 2026-07-20

limit 契约修真（R9 专项第 2 包）：manual_limit/limit 第一次真实生效（翻页驱动 ceil(limit/20) 页+service 截断·花费上限语义）+ 满页追页机制退役 + MCP 校验对齐/总闸默认 10 页 + result 4 如实反馈字段 + DIFF-007 闭合

`8a4fa7c` · `CHG-040` · [PR #55](https://github.com/alvinswen/X-Watcher/pull/55)

### [v1.36.0] · 2026-07-20

测试隔离加固（R9 专项首包 · 测试地基）：熔断器单例 autouse 保存/还原（scraper flaky 真根因修复）+ TaskRegistry 收敛单一 fixture + 幻影开关 XWATCHER_DATA_LAYER 清理（109 行/34 文件归零 · 守卫 2 文件保留）+ 数据根定向隔离（tests/sync）

`4689a0b` · `CHG-039` · [PR #54](https://github.com/alvinswen/X-Watcher/pull/54)

## 重构专项 R1–R8（v1.25.0 – v1.35.0）

### [v1.35.0] · 2026-07-20

工程化收口：cli 安装态修复 + ruff 全规则门禁上线 + tests 重组 + storage 原语直测

`903efdd` · `CHG-038` · [PR #53](https://github.com/alvinswen/X-Watcher/pull/53)

### [v1.34.0] · 2026-07-19

REST 错误处理统一：三代 500 归一 + 全局兜底 + 异常原文外泄堵漏

`59e94d5` · `CHG-037` · [PR #52](https://github.com/alvinswen/X-Watcher/pull/52)

### [v1.33.0] · 2026-07-19

web 前端重构：视觉收敛 + 依赖治理 + 测试钩子基建

`e391330` · `CHG-036` · [PR #51](https://github.com/alvinswen/X-Watcher/pull/51)

### [v1.32.0] · 2026-07-17

REST 契约质量集中收口：admin 响应 Pydantic 化 + DeleteResponse 谎言修正 + 孤儿路由全链删除 + json_encoders 迁移

`43b7198` · `CHG-035` · [PR #50](https://github.com/alvinswen/X-Watcher/pull/50)

### [v1.31.0] · 2026-07-17

FileSubjectStore 类型收敛：SubjectRepoProtocol 全量收口 + 34 处获取点单点化

`3903ff8` · `CHG-034` · [PR #49](https://github.com/alvinswen/X-Watcher/pull/49)

### [v1.30.0] · 2026-07-16

scraper 域 god-file 拆分：scraping_service 拆 3 服务 + client.py 重试归一

`a6f4a0a` · `CHG-033` · [PR #48](https://github.com/alvinswen/X-Watcher/pull/48)

### [v1.29.0] · 2026-07-15

抓取门面收尾：连接生命周期治理 + 统计查询收敛

`2157243` · `CHG-032` · [PR #47](https://github.com/alvinswen/X-Watcher/pull/47)

### [v1.28.0] · 2026-07-15

manual_limit 双门面修复：服务层下沉统一生效

`f2d174d` · `CHG-031` · [PR #46](https://github.com/alvinswen/X-Watcher/pull/46)

### [v1.27.0] · 2026-07-14

MCP 契约防护 + 样板统一：schema 快照 golden 先建闸 + subject_tools 执行器 + 常量/助手收敛

`1c67a00` · `CHG-030` · [PR #45](https://github.com/alvinswen/X-Watcher/pull/45)

### [v1.26.0] · 2026-07-13

性能止血：FileTweetStore 构造期全量重建移出 + 读侧有界缓存 + 任务清理接线 + Prometheus 归一

`8dfa956` · `CHG-029` · [PR #44](https://github.com/alvinswen/X-Watcher/pull/44)

### [v1.25.0] · 2026-07-13

清除 DB+LLM 双时代脚手架残留

`2965763` · `CHG-028` · [PR #43](https://github.com/alvinswen/X-Watcher/pull/43)

## 工程债治理专项 · mypy 棘轮 14 包（v1.11.0 – v1.24.1）

### [v1.24.1] · 2026-07-12

DIFF-006 关闭 · 删 summarization 孤儿双类

`458e148` · `—（轻流程 · 无 CHG 包）` · [PR #42](https://github.com/alvinswen/X-Watcher/pull/42)

### [v1.24.0] · 2026-07-12

撤 mypy-baseline 记账机制·门禁切全局裸 mypy strict 0 error

`3f6a548` · `CHG-027` · [PR #41](https://github.com/alvinswen/X-Watcher/pull/41)

### [v1.23.0] · 2026-07-12

user + preference + 横切基础设施 mypy 通用类型债清偿

`185e443` · `CHG-026` · [PR #40](https://github.com/alvinswen/X-Watcher/pull/40)

### [v1.22.0] · 2026-07-11

读侧仓储四域 mypy 通用类型债清偿

`2f59dac` · `CHG-025` · [PR #39](https://github.com/alvinswen/X-Watcher/pull/39)

### [v1.21.0] · 2026-07-11

api 域 mypy 通用类型债清偿

`9a52175` · `CHG-024` · [PR #38](https://github.com/alvinswen/X-Watcher/pull/38)

### [v1.20.0] · 2026-07-10

sync 域 mypy 通用类型债清偿

`3af29c3` · `CHG-023` · [PR #36](https://github.com/alvinswen/X-Watcher/pull/36)

### [v1.19.0] · 2026-07-10

MCP 层 + 议题域 mypy 通用类型债清偿

`b9f752d` · `CHG-022` · [PR #35](https://github.com/alvinswen/X-Watcher/pull/35)

### [v1.18.0] · 2026-07-09

database 根定义方 + 切换中枢 + 测试地基终局清偿

`faf8fef` · `CHG-021` · [PR #34](https://github.com/alvinswen/X-Watcher/pull/34)

### [v1.17.0] · 2026-07-09

MCP 层会话脚手架脱钩

`9b6cdf1` · `CHG-020` · [PR #33](https://github.com/alvinswen/X-Watcher/pull/33)

### [v1.16.0] · 2026-07-08

api+cli+scripts 会话脚手架脱钩

`64eaa5f` · `CHG-019` · [PR #32](https://github.com/alvinswen/X-Watcher/pull/32)

### [v1.15.0] · 2026-07-07

scraper 域数据库会话脚手架脱钩

`c9bbcdc` · `CHG-018` · [PR #31](https://github.com/alvinswen/X-Watcher/pull/31)

### [v1.14.0] · 2026-07-07

database 纯叶子 sqlalchemy 死实现删除

`52138c7` · `CHG-017` · [PR #30](https://github.com/alvinswen/X-Watcher/pull/30)

### [v1.13.0] · 2026-07-06

抓取域 file 方案链 mypy 存量类型债清偿

`02d7dd5` · `CHG-016` · [PR #29](https://github.com/alvinswen/X-Watcher/pull/29)

### [v1.12.0] · 2026-07-06

核心数据层在用文件方案链 mypy 存量类型债清偿

`3d1a5b6` · `CHG-015` · [PR #28](https://github.com/alvinswen/X-Watcher/pull/28)

### [v1.11.0] · 2026-07-05

mypy 门禁恢复 + mypy-baseline 棘轮地基

`e71f05d` · `CHG-014` · [PR #27](https://github.com/alvinswen/X-Watcher/pull/27)

## 安全加固（v1.10.0）

### [v1.10.0] · 2026-07-04

MCP 提示词注入加固（R1+R2）·安全加固三件套收官

`d78bfa6` · `CHG-013` · [PR #26](https://github.com/alvinswen/X-Watcher/pull/26)

## L4 Self-Harness 自证体系（v1.7.0 – v1.9.0）

### [v1.9.0] · 2026-07-04

L4 Self-Harness 路线图收官·剥离残留 summarization LLM 坐实 L2 零 LLM

`80f74c5` · `CHG-012` · [PR #25](https://github.com/alvinswen/X-Watcher/pull/25)

### [v1.8.0] · 2026-07-03

L4 Self-Harness 一期评估门闭环（P3 两包）

`df983d0` · `CHG-011 + CHG-011-B` · [PR #24](https://github.com/alvinswen/X-Watcher/pull/24)

### [v1.7.0] · 2026-07-02

L4 Self-Harness 溯源 + 反馈两层地基落地

`becb175` · `CHG-009 + CHG-009-C + CHG-009-B + CHG-010` · [PR #23](https://github.com/alvinswen/X-Watcher/pull/23)

## Subject 议题体系（v1.3.0 – v1.6.0）

### [v1.6.0] · 2026-06-30

subject digest 发布时间轴（time_axis=publish）真正落地 + MCP 三字段 JSON 容错

`cb5a1a0` · `CHG-008` · [PR #22](https://github.com/alvinswen/X-Watcher/pull/22)

### [v1.5.0] · 2026-06-29

Subject 议题总结架构掉头为 skill 驱动 v2 pivot

`a330efb` · `CHG-007`

### [v1.4.1] · 2026-06-28

L1 digest 句中截断修复

`ffd2e0c` · `ESC-002 修复 · bug fix` · [PR #21](https://github.com/alvinswen/X-Watcher/pull/21)

### [v1.4.0] · 2026-06-28

Subject L2 活综述二期

`4829f00` · `CHG-006` · [PR #20](https://github.com/alvinswen/X-Watcher/pull/20)

### [v1.3.1] · 2026-06-27

死代码清理 · topic/scheduler 下线残留

`6af92ca` · `CHG-005` · [PR #19](https://github.com/alvinswen/X-Watcher/pull/19)

### [v1.3.0] · 2026-06-27

首个 minor · Subject 议题 continuous-query 一期

`9037876` · `CHG-004` · [PR #18](https://github.com/alvinswen/X-Watcher/pull/18)

## 项目接入与精简（v1.0.0 – v1.2.3）

### [v1.2.3] · 2026-06-27

UI 文案对齐

`4a91c91` · `OPT-001` · [PR #17](https://github.com/alvinswen/X-Watcher/pull/17)

### [v1.2.2] · 2026-06-26

配置收口 · 代码原生默认对齐 file 模式

`5252656` · `CHG-003`

### [v1.2.1] · 2026-06-25

安全+正确性后端硬修

`293b3d1` · `CHG-002` · [PR #15](https://github.com/alvinswen/X-Watcher/pull/15)

### [v1.2.0] · 2026-06-24

首个代码发布基线 · 下线 M03 调度与任务 + M05 主题聚合

`acec4bc` · `CHG-001` · [PR #14](https://github.com/alvinswen/X-Watcher/pull/14)

### [v1.1.0] · 2026-06-24

docs-only · 存量文档基建完成

`3ba5ce5` · `CHG-001`

### [v1.0.0] · 2026-06-24

项目接入首次基线（6 维侦察 · 核心架构黑名单 8 项 · 领域术语 14 对 · 墨纸视觉基线）

`3ba5ce5` · `首次基线建立（/init-project 接入 X-Watcher）`

