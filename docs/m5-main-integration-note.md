# m5-file-layer-wiring → main 集成提醒

> 待办性质的"已知集成点"备忘。日后把 `m5-file-layer-wiring` 合并 / rebase 到 `main` 时先读本文件，避免被冲突吓到。
> 记录日期：2026-06-21

---

## 背景

`main` 已通过 PR #2（commit `5fcdc5d` + `dcc2827`，merge `dc46eb4`）合入"`save_summaries` 入库前确定性验证门 + `rejected` 回灌接缝"。

该 PR 是从 m5 切出后 **rebase 到 main 基线** 落地的，因此它按 **main 的写法** 用 `SummarizationRepository(session)` 直连。而 `m5-file-layer-wiring` 把同一处重构成了 data-layer 的 `get_summary_repo(session)`。

→ **两边都改了同一个文件的同一区域，合并时会冲突。**

## 冲突点（唯一）

**文件**：`src/mcp/tools/summarization_tools.py`，`save_summaries` 内部。

| | main（已合入）| m5（本分支）|
|---|---|---|
| import | `from src.summarization.infrastructure.repository import SummarizationRepository` + `from src.summarization.domain.summary_verification import verify_translation` | `from src.data_layer.provider import get_summary_repo` |
| repo 构造 | `repo = SummarizationRepository(session)` | `repo = get_summary_repo(session)` |
| 校验逻辑 | 有验证门：批量回查原文 + `verify_translation` + `rejected` 返回 | 无 |

## 解决办法（合并时这样取舍）

**两者合一，不是二选一**：

1. **repo 构造走 m5 的 `get_summary_repo(session)`**（保留 m5 的 data-layer 接线）。
2. **保留 main 的验证门逻辑**：
   - import 同时保留 `get_summary_repo`、`verify_translation`、`TweetOrm`（去掉 main 那条 `SummarizationRepository` 直连 import，因为 repo 改走 provider）。
   - 保留 `save_summaries` 里"按 tweet_id 批量回查原文 → `verify_translation` → 失败进 `errors`/`rejected`、不入库"的整段。
   - 保留返回里的 `rejected` 字段。

## 无冲突、但会随合并带入 m5 的新文件

- `src/summarization/domain/summary_verification.py`（验证门纯函数）— 新文件，无冲突。
- `tests/summarization/test_summary_verification.py` — 新文件，无冲突。
- `docs/drift-log.md` — 新文件（m5 当前没有），无冲突。
- 合并后建议跑：`pytest tests/summarization/test_summary_verification.py tests/mcp/test_summarization_tools.py -q`（基线应 25 passed）。

## 编排层（不在版本库）

`/scrape-and-translate` 的"失败回灌重生成"Step 5.5 在 gitignored 的 `.claude/commands/`，只在本机生效，**不随任何分支合并流动**。如果换机 / 协作需要它，单独同步该命令文件。

## 长度比阈值口径

验证门长度比是校准后的 **25%–150%**（`summary_verification.py` 顶部 `LENGTH_RATIO_MIN/MAX`），不是 slash-command 字面的 60–120%（实测忠实英译中字符比约 0.33，60% 下限会误杀）。改阈值改这两个常量即可。
