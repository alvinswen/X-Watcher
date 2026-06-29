---
name: xw-classify
description: Classify new tweets into active X-Watcher subjects and write subject matches through the A2 MCP tools.
---

# xw-classify

Use this skill when you need to assign newly browsed tweets to one or more active X-Watcher subjects.

## Authority And Scope

The authoritative schema is `deliverables/2026-06-28-CHG-007-subject-skill-driven-A2.done/04-接口契约.md`. Any parameter table below is only an extract for execution clarity; if there is a conflict, follow the A2 contract.

This skill runs a single execution round: 取数 -> 动脑 -> 回写. It does not self-loop, does not define a trigger cadence, and does not store cursor state in the repository. Scheduling is external, such as loop orchestration, cron, or manual invocation. The cursor `T` is an external input owned by the caller.

## Inputs

- `cursor_T`: optional external cursor timestamp. Process tweets with `created_at > cursor_T`.
- `date_range`: optional explicit date range for browsing pages.
- `subject_ids`: optional subset of active subjects. If absent, use all active subjects.

If `cursor_T` is absent, warn the caller and process only today's publish-date pages for this one round.

## Execution Steps

1. Get pending classification targets.
   - Call `get_pending_jobs`.
   - Keep only subjects with `pending_classify=true`.
   - If `subject_ids` was provided, intersect it with the pending set.
   - Stop with a "nothing to classify" report if the final set is empty.

2. Load active subjects.
   - Call `list_subjects(status="active")`.
   - Build an in-memory subject catalog from each subject's id, title, description, keywords, and exclusions.
   - Only classify against active subjects that are also in the pending set selected in step 1.

3. Browse candidate tweets.
   - Use `browse_tweets(date=..., page=...)` over the required publish-date pages.
   - Filter browsed items by `created_at > T` when `cursor_T` is present.
   - The browse result exposes `created_at` only and does not expose `ingested`; therefore this skill uses a publish-axis approximation. Duplicate classification is deduped server-side by `put_subject_matches`.

4. Classify semantically.
   - Compare tweet text, media context, author, quoted text, and linked context against the subject catalog.
   - Use multi-label classification: one tweet may match zero, one, or many subjects.
   - Prefer precision over recall for weak or ambiguous matches.
   - For each accepted match, prepare a short reason tied to the subject definition.

5. Write matches.
   - Batch by `subject_id`.
   - Pass `tweet_ids` as a comma-separated string.
   - Do not pass service-generated fields such as match time.
   - Trust a successful write response; no readback is required for classification.

6. Report.
   - Summarize browsed count, filtered count, matched count by subject, skipped ambiguous count, and failed subject batches.
   - Include the highest processed `created_at` so the external caller may decide the next cursor.

## Tool Contract Extract

### `get_pending_jobs`

No arguments are required.

### `list_subjects`

```json
{
  "status": "active"
}
```

### `browse_tweets`

```json
{
  "date": "2026-06-29",
  "page": 1
}
```

### `put_subject_matches`

```json
{
  "subject_id": "s_ai",
  "tweet_ids": "tw_1001",
  "relevance": 0.95,
  "reason": "OpenAI 发布新推理模型，属 AI 模型动态"
}
```

Success response:

```json
{
  "success": true,
  "data": {
    "written": 1,
    "subject_id": "s_ai",
    "pending_classify": false
  }
}
```

## Few-Shot Run

### Input Context

The caller provides `cursor_T=2026-06-29T00:00:00Z`. `get_pending_jobs` reports `s_ai` with `pending_classify=true`, and `list_subjects(status="active")` returns an AI model dynamics subject.

### Candidate Tweet

```json
{
  "id": "tw_1001",
  "created_at": "2026-06-29T02:13:00Z",
  "text": "OpenAI 发布 o5 推理模型，长链推理表现明显提升。"
}
```

### Reasoning

`tw_1001` is newer than `cursor_T` and directly describes an OpenAI reasoning model release. It matches `s_ai` with high relevance.

### Write

```json
{
  "subject_id": "s_ai",
  "tweet_ids": "tw_1001",
  "relevance": 0.95,
  "reason": "OpenAI 发布新推理模型，属 AI 模型动态"
}
```

### Expected Result

```json
{
  "success": true,
  "data": {
    "written": 1,
    "subject_id": "s_ai",
    "pending_classify": false
  }
}
```

## Failure And Retry Rules

- Partial success: keep successful subject batches and report failed subject batches with their subject ids and tool errors.
- `validation` with missing ids: skip the failed subject batch, continue other subjects, and report the missing ids.
- `not_found` or permission errors: stop the round and report the blocking error.
- Any uncertain semantic match should be omitted rather than written with low confidence.
