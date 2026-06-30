---
name: xw-digest
description: Generate interval subject digests from classified X-Watcher matches and write them through the A2 MCP tools.
---

# xw-digest

Use this skill when a subject needs an interval digest over already classified matches.

## Authority And Scope

The authoritative schema is `deliverables/2026-06-28-CHG-007-subject-skill-driven-A2.done/04-接口契约.md`. Any parameter table below is only an extract for execution clarity; if there is a conflict, follow the A2 contract.

Before using this skill, ensure the target subject has run `xw-classify` to the latest available tweet set.

This skill runs a single execution round: 取数 -> 动脑 -> 回写 -> 校验. It does not self-loop, does not define a trigger cadence, and does not store cursor state in the repository. Scheduling is external, such as loop orchestration, cron, or manual invocation. The cursor `T` and any explicit interval are external inputs owned by the caller.

## Inputs

- `subject_id`: required target subject.
- `interval_start`: optional explicit interval start.
- `interval_end`: optional explicit interval end. If absent, use the current caller-provided time.
- `time_axis`: optional; defaults to `ingest`, may be `publish` to filter candidates and validate citations by each tweet's publish time (created_at). When publish, step 2 must also pass time_axis=publish so the locked candidate set matches the write-side validation.

## Execution Steps

1. Decide the interval.
   - If the caller provides both `interval_start` and `interval_end`, use them.
   - Otherwise call `get_subject_digest(subject_id)`.
   - If a prior digest exists, use its latest `interval_end` as the new `interval_start`, and use caller-provided now as `interval_end`.
   - If no prior digest exists, call `get_subject_feed(subject_id)` and take the earliest matched item time as `interval_start`.
   - If no feed item exists, skip writing and report "no classified matches".

2. Lock the candidate set.
   - Call `get_subject_feed(subject_id, since=interval_start, until=interval_end, time_axis=time_axis)`. When `time_axis=publish`, the returned candidates are scoped by publish time, matching the write-side validation.
   - Treat the returned tweet ids as the only citation candidate set for this run.
   - If the returned set is empty, skip writing and report the empty interval.

3. Generate the digest.
   - Write a concise `digest_text` no longer than 4000 characters.
   - Do not truncate mid-sentence; shrink and rewrite before calling the write tool.
   - Build `highlights` as a JSON array string. Each highlight has a `point` and `cited_tweet_ids`.
   - Build `cited` as a comma-separated string.
   - Every id in `cited` and every id in highlight `cited_tweet_ids` must be a subset of the locked candidate ids.

4. Write the digest.
   - Call `put_subject_digest`.
   - Do not pass service-generated metadata fields.
   - This endpoint is append-only: rerunning the same interval can add another digest record. The latest record is determined by `interval_end` and generated time on the server.

5. Validate the write.
   - Call `get_subject_digest(subject_id, start=interval_start, end=interval_end)`.
   - Confirm the returned interval and digest body match the just-written interval and body.
   - If validation fails, report the mismatch instead of inventing a local correction.

## Tool Contract Extract

### `get_subject_digest`

Latest digest:

```json
{
  "subject_id": "s_ai"
}
```

Interval readback:

```json
{
  "subject_id": "s_ai",
  "start": "2026-06-29T00:00:00Z",
  "end": "2026-06-29T06:00:00Z"
}
```

### `get_subject_feed`

```json
{
  "subject_id": "s_ai",
  "since": "2026-06-29T00:00:00Z",
  "until": "2026-06-29T06:00:00Z"
}
```

### `put_subject_digest`

```json
{
  "subject_id": "s_ai",
  "interval_start": "2026-06-29T00:00:00Z",
  "interval_end": "2026-06-29T06:00:00Z",
  "time_axis": "ingest",
  "digest_text": "本区间 AI 模型动态：OpenAI 发布 o5 推理模型，主打长链推理；社区开始对比其与既有模型的基准表现。",
  "highlights": "[{\"point\":\"OpenAI 发布 o5 推理模型\",\"cited_tweet_ids\":[\"tw_1001\"]},{\"point\":\"社区对比基准表现\",\"cited_tweet_ids\":[\"tw_1003\"]}]",
  "cited": "tw_1001,tw_1003"
}
```

Success response:

```json
{
  "success": true,
  "data": {
    "subject_id": "s_ai",
    "interval_start": "2026-06-29T00:00:00Z",
    "interval_end": "2026-06-29T06:00:00Z"
  }
}
```

## Few-Shot Run

### Input Context

`xw-classify` has already written the latest AI subject matches. The previous digest ended at `2026-06-29T00:00:00Z`, and the caller asks to digest through `2026-06-29T06:00:00Z` on the default ingest axis.

### Locked Feed Candidates

```json
[
  {
    "id": "tw_1001",
    "text": "OpenAI 发布 o5 推理模型，长链推理表现明显提升。"
  },
  {
    "id": "tw_1003",
    "text": "社区开始对比 o5 与既有模型的基准表现。"
  }
]
```

### Write

```json
{
  "subject_id": "s_ai",
  "interval_start": "2026-06-29T00:00:00Z",
  "interval_end": "2026-06-29T06:00:00Z",
  "time_axis": "ingest",
  "digest_text": "本区间 AI 模型动态：OpenAI 发布 o5 推理模型，主打长链推理；社区开始对比其与既有模型的基准表现。",
  "highlights": "[{\"point\":\"OpenAI 发布 o5 推理模型\",\"cited_tweet_ids\":[\"tw_1001\"]},{\"point\":\"社区对比基准表现\",\"cited_tweet_ids\":[\"tw_1003\"]}]",
  "cited": "tw_1001,tw_1003"
}
```

### Expected Result

```json
{
  "success": true,
  "data": {
    "subject_id": "s_ai",
    "interval_start": "2026-06-29T00:00:00Z",
    "interval_end": "2026-06-29T06:00:00Z"
  }
}
```

## Failure And Retry Rules

- `digest_text` over 4000 characters: shrink and rewrite the text, preserving sentence boundaries, then retry once.
- Citation ids outside the locked candidate set: drop or recompute unsupported citations, then retry once.
- `not_found` or permission errors: stop the round and report the blocking error.
- Empty interval: do not write; report the interval and candidate count.
- Readback mismatch after a successful write: report the mismatch and do not attempt extra writes unless the caller explicitly starts a new round.
