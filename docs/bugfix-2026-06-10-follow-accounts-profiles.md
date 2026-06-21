# Bugfix：get_follow_accounts_info(profiles) ORM 属性名错误

> 日期：2026-06-10
> 影响范围：MCP 工具 `get_follow_accounts_info` 的 `profiles` 分支（admin 权限）
> 状态：已修复，已补测试，改动在 `m5-file-layer-wiring` 分支工作区（提交由用户决定）

---

## 现象

调用 `get_follow_accounts_info(info_type="profiles")` 必然失败：

```json
{"success": false, "error": "查询失败: type object 'XUserProfileOrm' has no attribute 'bio'", "error_type": "internal"}
```

其余三个 info_type（`stats` / `tweet_time_range` / `analysis`）均正常。

发现路径：分析"关注账号是否包含 tdinh_me"时想用 profiles 口径查档案，首次触发该分支即报错（改用 stats 口径完成了当时的查询）。

## 根因

`src/mcp/tools/admin_tools.py` 的 profiles 分支 select 了 **两个 ORM 上不存在的属性**：

| 代码引用 | ORM 实际字段（`src/database/x_user_profile_model.py`） | 字段语义 |
|---|---|---|
| `XUserProfileOrm.bio` | `description`（line 43） | 个人简介 |
| `XUserProfileOrm.tweet_count` | `statuses_count`（line 55） | 推文总数 |

- 工具代码按 TwitterAPI.io 的惯用字段名（bio / tweet_count）想当然书写，而 ORM 落库时采用了 API 原始响应的另一套命名（description / statuses_count）。
- select 参数从左到右求值，先炸在 `bio`，因此报错只暴露第一个；只修 `bio` 会接着炸 `tweet_count`。
- 该分支此前**零测试覆盖**（仅"工具注册完整性"测试提到工具名），属于 never-exercised 分支——写完后从未被真实调用过，错误潜伏至首次使用。

## 修复

`src/mcp/tools/admin_tools.py` profiles 分支两处（select 列 + 结果字典取值）：

```python
# 修复前 → 修复后
XUserProfileOrm.bio          → XUserProfileOrm.description
XUserProfileOrm.tweet_count  → XUserProfileOrm.statuses_count
"bio": r.bio                 → "bio": r.description
"tweet_count": r.tweet_count → "tweet_count": r.statuses_count
```

**对外 JSON key 保持 `bio` / `tweet_count` 不变**：该分支从未成功返回过，无既有消费者；对外用 X 平台通用术语、内部映射 ORM 字段，是合理的展示层命名。

## 顺带修复的存量问题

`tests/mcp/test_mcp_integration.py::TestToolRegistration::test_all_resources_registered` 存量失败：代码有意新增了 `xwatcher://recipes/claude-code-topic-review` 资源，但测试期望集合未同步。已补入该 URI。（用 git stash 验证过该失败与本次 bugfix 无关。）

## 测试与验证

按 TDD 流程执行（先红后绿）：

1. 新增 `tests/mcp/test_mcp_integration.py::TestFollowAccountsInfoIntegration::test_profiles_returns_cached_profile_fields`——seed 一条 `XUserProfileOrm`，调用工具断言 bio/tweet_count 映射正确；
2. 修复前运行：失败信息与线上一字不差（复现成功）；
3. 修复后运行：通过；
4. `tests/mcp/` 全量：63 passed / 0 failed；
5. `ruff check` 两个改动文件：无告警；
6. 端到端实测：用修复后代码直连真实 Postgres，返回 64 条档案、抽样核对 bio / tweet_count / followers_count 字段值正确。

注意：**stdio MCP server 进程不会热更新**——修复当时的会话内再调该工具仍报旧错，需重启会话/MCP 进程后生效。

## 改动文件清单

| 文件 | 改动 |
|---|---|
| `src/mcp/tools/admin_tools.py` | profiles 分支 4 处属性名修正（2 列 + 2 取值） |
| `tests/mcp/test_mcp_integration.py` | 新增 profiles 集成测试类；资源注册测试补 topic-review URI；顶部补 `XUserProfileOrm` import |

## 经验教训

1. **写 ORM 查询前先打开模型文件核对字段名**，不要按外部 API / 直觉惯用名书写——本项目 ORM 命名跟随 TwitterAPI.io 原始响应（statuses_count），与社区惯用名（tweet_count）不一致。这是项目 CLAUDE.md "P007 实证驱动（先 grep 再写）"的又一实例。
2. **新增工具/分支必须至少配一条 happy-path 集成测试**：本 bug 在零覆盖分支里潜伏到首次真实调用才暴露；conftest 的 ORM 注册 import 列表也未包含 `XUserProfileOrm`（测试文件自行 import 可绕过，但易踩坑）。
3. **同一处代码按同一错误模式扫全**：select 里两个字段错同源（bio + tweet_count），报错只暴露第一个；修复时按"同批次同类错误"原则把整个 select 的列逐一对照 ORM 核验，避免修一个炸下一个。
