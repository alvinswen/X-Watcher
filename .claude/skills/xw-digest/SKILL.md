---
name: xw-digest
description: Generate interval subject digests from classified X-Watcher matches and write them through the A2 MCP tools.
playbook_version: 1.0.0
---

# xw-digest

Use this skill when a subject needs an interval digest over already classified matches.

## Authority And Scope

The authoritative schema is `deliverables/2026-06-28-CHG-007-subject-skill-driven-A2.done/04-接口契约.md`. Any parameter table below is only an extract for execution clarity; if there is a conflict, follow the A2 contract.

The provenance extension is defined by CHG-009-B. When this skill writes a digest, `playbook_id` is the fixed literal `xw-digest`, `playbook_version` is read from this file's front-matter, and `generated_at` / `validator_version` are never passed because the service fills them.

Before using this skill, ensure the target subject has run `xw-classify` to the latest available tweet set.

This skill runs a single execution round: 取数 -> 动脑 -> 回写 -> 校验. It does not self-loop, does not define a trigger cadence, and does not store cursor state in the repository. Scheduling is external, such as loop orchestration, cron, or manual invocation. The cursor `T` and any explicit interval are external inputs owned by the caller.

## Inputs

- `subject_id`: required target subject.
- `interval_start`: optional explicit interval start.
- `interval_end`: optional explicit interval end. If absent, use the current caller-provided time.
- `time_axis`: optional; defaults to `ingest`, may be `publish` to filter candidates and validate citations by each tweet's publish time (created_at). Step 2 and the write step must use the same effective `time_axis` value so the candidate-set口径 matches the write-side validation.

## Execution Steps

1. Decide the interval.
   - If the caller provides both `interval_start` and `interval_end`, use them.
   - Otherwise call `get_subject_digest(subject_id)`.
   - If a prior digest exists, use its latest `interval_end` as the new `interval_start`, and use caller-provided now as `interval_end`.
   - If no prior digest exists, call `get_subject_feed(subject_id)` and take the earliest matched item time as `interval_start`.
   - If no feed item exists, skip writing and report "no classified matches".

2. Lock the authoritative candidate set for provenance and citation bounds.
   - Let `effective_time_axis` be the caller-provided `time_axis`, or `ingest` when omitted.
   - Call `get_subject_candidate_set(subject_id, time_axis=effective_time_axis, interval_start=interval_start, interval_end=interval_end)`.
   - Copy `candidate_ids` and `candidate_set_hash` directly from the successful response. Do not compute a digest candidate hash inside this skill, and do not use `get_subject_feed` ids for `candidate_set_hash`.
   - If `count` is 0, skip writing and report the empty interval.
   - If this tool call fails, treat it as provenance assembly failure: continue the existing feed-based main artifact flow without provenance and emit a warning.

3. Load feed content for writing.
   - Call `get_subject_feed(subject_id, since=interval_start, until=interval_end, time_axis=effective_time_axis)` to get tweet text and context for reasoning.
   - This feed call is a body-text data flow only. It may be paged or shaped for reading, but it is never the source of `candidate_set_hash`.
   - Every id in `cited` and every id in highlight `cited_tweet_ids` must be a subset of the authoritative `candidate_ids` from step 2 when provenance is available.
   - If provenance is unavailable, keep the existing behavior: cite only ids present in the loaded feed content.

4. Generate the digest.
   - Write a concise `digest_text` no longer than 4000 characters.
   - Do not truncate mid-sentence; shrink and rewrite before calling the write tool.
   - Build `highlights` as a JSON array string. Each highlight has a `point` and `cited_tweet_ids`.
   - Build `cited` as a comma-separated string.
   - Every id in `cited` and every id in highlight `cited_tweet_ids` must be a subset of the locked candidate ids.

5. Assemble provenance.
   - Read the full current `.claude/skills/xw-digest/SKILL.md` file, including this front-matter, and compute `prompt_hash` as a lowercase SHA256 hex digest of the file bytes.
   - Set `playbook_id` to `xw-digest`; set `playbook_version` to the front-matter value `1.0.0`.
   - Set `candidate_set_hash` to the exact value returned by `get_subject_candidate_set`.
   - Set `candidate_ids` to the returned candidate ids joined by commas for the MCP call.
   - Fill `model_name` and `model_version` with true runtime values if available; if unavailable, leave them null or omit them.
   - If the self file cannot be read, the prompt hash cannot be computed, or the candidate-set tool failed, keep the main artifact and write without all seven provenance arguments while emitting a warning.

6. Write the digest.
   - Call `put_subject_digest`.
   - Pass the same `effective_time_axis` used in step 2.
   - If provenance assembly succeeded, append the seven provenance arguments: `playbook_id`, `playbook_version`, `prompt_hash`, `candidate_set_hash`, `candidate_ids`, `model_name`, and `model_version`.
   - Do not pass service-generated metadata fields.
   - This endpoint is append-only: rerunning the same interval can add another digest record. The latest record is determined by `interval_end` and generated time on the server.

7. Validate the write.
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

### `get_subject_candidate_set`

Use the same `time_axis`, `interval_start`, and `interval_end` that will be sent to `put_subject_digest`.

```json
{
  "subject_id": "s_ai",
  "time_axis": "ingest",
  "interval_start": "2026-06-29T00:00:00Z",
  "interval_end": "2026-06-29T06:00:00Z"
}
```

Success response:

```json
{
  "success": true,
  "data": {
    "candidate_ids": ["tw_1001", "tw_1003"],
    "candidate_set_hash": "5314ebf09a1d0b2d6b914866c8fae64b0a9395113f17b99d20e22f4e5e0b8232",
    "count": 2,
    "time_axis": "ingest",
    "interval_start": "2026-06-29T00:00:00+00:00",
    "interval_end": "2026-06-29T06:00:00+00:00",
    "skipped_no_publish_time": 0
  }
}
```

### `put_subject_digest`

The hash values below are illustrative examples of field shape only; runtime calls must compute `prompt_hash` fresh and copy `candidate_set_hash` from `get_subject_candidate_set`.

```json
{
  "subject_id": "s_ai",
  "interval_start": "2026-06-29T00:00:00Z",
  "interval_end": "2026-06-29T06:00:00Z",
  "time_axis": "ingest",
  "digest_text": "本区间 AI 模型动态：OpenAI 发布 o5 推理模型，主打长链推理；社区开始对比其与既有模型的基准表现。",
  "highlights": "[{\"point\":\"OpenAI 发布 o5 推理模型\",\"cited_tweet_ids\":[\"tw_1001\"]},{\"point\":\"社区对比基准表现\",\"cited_tweet_ids\":[\"tw_1003\"]}]",
  "cited": "tw_1001,tw_1003",
  "playbook_id": "xw-digest",
  "playbook_version": "1.0.0",
  "prompt_hash": "8c1a37f34a1ffd69269ac973806f824d0f952ea64eec3a808ff0325911acafe9",
  "candidate_set_hash": "5314ebf09a1d0b2d6b914866c8fae64b0a9395113f17b99d20e22f4e5e0b8232",
  "candidate_ids": "tw_1001,tw_1003",
  "model_name": null,
  "model_version": null
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

Before reading feed text, call `get_subject_candidate_set(subject_id="s_ai", time_axis="ingest", interval_start="2026-06-29T00:00:00Z", interval_end="2026-06-29T06:00:00Z")` and copy `candidate_ids=["tw_1001","tw_1003"]` plus `candidate_set_hash`. The feed below is for body text, not for hash calculation.

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
  "cited": "tw_1001,tw_1003",
  "playbook_id": "xw-digest",
  "playbook_version": "1.0.0",
  "prompt_hash": "8c1a37f34a1ffd69269ac973806f824d0f952ea64eec3a808ff0325911acafe9",
  "candidate_set_hash": "5314ebf09a1d0b2d6b914866c8fae64b0a9395113f17b99d20e22f4e5e0b8232",
  "candidate_ids": "tw_1001,tw_1003",
  "model_name": null,
  "model_version": null
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
- Provenance assembly failure, such as `get_subject_candidate_set` returning `not_found` / `validation` or being unable to read `.claude/skills/xw-digest/SKILL.md`, is a skill-side degradation path: write the same digest without the seven provenance arguments and warn that provenance was not produced.
- Service-side `validation` caused by a `candidate_set_hash` mismatch is not a degradation path. Report the service diagnostic, including the system recomputed count, hash prefix, and sample ids when present; do not silently retry by dropping provenance.
- `not_found` or permission errors: stop the round and report the blocking error.
- Empty interval: do not write; report the interval and candidate count.
- Readback mismatch after a successful write: report the mismatch and do not attempt extra writes unless the caller explicitly starts a new round.
