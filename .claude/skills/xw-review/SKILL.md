---
name: xw-review
description: Update cumulative X-Watcher subject reviews from classified matches with optimistic version writes through the A2 MCP tools.
playbook_version: 1.0.0
---

# xw-review

Use this skill when a subject needs its cumulative review updated from new classified matches.

## Authority And Scope

The authoritative schema is the live MCP tool signatures in `src/mcp/tools/subject_tools.py`. Any parameter table below is only an extract for execution clarity; if there is a conflict, follow the tool signatures in `src/mcp/tools/subject_tools.py`.

The provenance extension is defined by CHG-009-B. When this skill writes a review, `playbook_id` is the fixed literal `xw-review`, `playbook_version` is read from this file's front-matter, and `generated_at` / `validator_version` are never passed because the service fills them.

Before using this skill, ensure the target subject has run `xw-classify` to the latest available tweet set.

This skill runs a single execution round: 取数 -> 动脑 -> 回写 -> 校验. It does not self-loop, does not define a trigger cadence, and does not store cursor state in the repository. Scheduling is external, such as loop orchestration, cron, or manual invocation. The cursor `T` and subject selection are external inputs owned by the caller.

## Inputs

- `subject_id`: optional explicit target subject. If absent, use pending review subjects.
- `covered_until`: optional caller override for the lower bound. Normally use the current review's `covered_until`.

## Execution Steps

1. Select review targets.
   - Unless `subject_id` is specified, call `get_pending_jobs`.
   - Keep only subjects with `pending_review=true`.
   - If `subject_id` is specified, process that subject directly.
   - Stop with a "nothing to review" report if no target remains.

2. Load the current review.
   - Call `get_subject_review(subject_id)`.
   - If no review exists, treat it as an empty shell with current version 0 and no `covered_until`.
   - If `covered_until` is null or absent, use all subject matches and write with `prev_version=0`.

3. Load new matches.
   - Call `get_subject_feed(subject_id, since=covered_until)` when `covered_until` exists.
   - If no new match exists, skip writing and report "no new version".
   - For citation validation, build a known subject match id set. If only the latest window was loaded, expand by paging `get_subject_feed(subject_id)` without `since` before selecting final cited ids.

4. Get the authoritative review candidate set.
   - Call `get_subject_candidate_set(subject_id, time_axis="review")`.
   - Copy `candidate_ids` and `candidate_set_hash` directly from the successful response. Do not compute a review candidate hash inside this skill, and do not use `get_subject_feed` ids for `candidate_set_hash`.
   - This is the provenance data flow. `get_subject_feed` remains the body-text and citation-validation data flow.
   - Every id in `cited` and every id in section `cited_tweet_ids` must be a subset of the authoritative review `candidate_ids` when provenance is available.
   - If this tool call fails, treat it as provenance assembly failure: continue the existing review write flow without provenance and emit a warning.

5. Merge cumulatively.
   - Preserve prior review knowledge and update it with new evidence rather than replacing the review with only the latest window.
   - Build `sections` as a JSON array string. Each section has a nonempty `title`, a nonempty `body`, and `cited_tweet_ids`.
   - Each section body must be no longer than 4000 characters. Rewrite before writing if needed.
   - Build `trend` as a JSON object string when trend information is available.
   - Build `cited` as a comma-separated string.
   - Every id in `cited` and every id in section `cited_tweet_ids` must be a subset of all known subject match ids.

6. Assemble provenance.
   - Read the full current `.claude/skills/xw-review/SKILL.md` file, including this front-matter, and compute `prompt_hash` as a lowercase SHA256 hex digest of the file bytes.
   - Set `playbook_id` to `xw-review`; set `playbook_version` to the front-matter value `1.0.0`.
   - Set `candidate_set_hash` to the exact value returned by `get_subject_candidate_set`.
   - Set `candidate_ids` to the returned candidate ids joined by commas for the MCP call.
   - Fill `model_name` and `model_version` with true runtime values if available; if unavailable, leave them null or omit them.
   - If the self file cannot be read, the prompt hash cannot be computed, or the candidate-set tool failed, keep the main artifact and write without all seven provenance arguments while emitting a warning.

7. Write the review.
   - Call `put_subject_review` with `prev_version` equal to the current review version.
   - Include `sections`, `covered_until`, and optional `trend` and `cited`.
   - If provenance assembly succeeded, append the seven provenance arguments: `playbook_id`, `playbook_version`, `prompt_hash`, `candidate_set_hash`, `candidate_ids`, `model_name`, and `model_version`.
   - Do not pass server-owned output fields.

8. Validate the write.
   - Call `get_subject_review(subject_id)`.
   - Confirm the returned version equals the version returned by the write response.
   - Confirm the review content reflects the sections and citations just written.

## Tool Contract Extract

### `get_pending_jobs`

No arguments are required.

### `get_subject_review`

```json
{
  "subject_id": "s_ai"
}
```

### `get_subject_feed`

New matches:

```json
{
  "subject_id": "s_ai",
  "since": "2026-06-29T00:00:00Z"
}
```

Full known match id set:

```json
{
  "subject_id": "s_ai"
}
```

### `get_subject_candidate_set`

For reviews, use the full review口径 and do not pass interval bounds.

```json
{
  "subject_id": "s_ai",
  "time_axis": "review"
}
```

Success response:

```json
{
  "success": true,
  "data": {
    "candidate_ids": ["tw_1001", "tw_1003", "tw_1010"],
    "candidate_set_hash": "5f08779df2d867b834d023108bf7b2747640c5324f3ae5273da010adbf9cc109",
    "count": 3,
    "time_axis": "review",
    "interval_start": null,
    "interval_end": null,
    "skipped_no_publish_time": 0
  }
}
```

### `put_subject_review`

The hash values below are illustrative examples of field shape only; runtime calls must compute `prompt_hash` fresh and copy `candidate_set_hash` from `get_subject_candidate_set`.

```json
{
  "subject_id": "s_ai",
  "prev_version": 7,
  "sections": "[{\"title\":\"模型能力演进\",\"body\":\"自上轮以来，o5 推理模型成为焦点，长链推理为主要卖点。\",\"cited_tweet_ids\":[\"tw_1001\"]},{\"title\":\"社区反应\",\"body\":\"社区围绕基准对比展开讨论。\",\"cited_tweet_ids\":[\"tw_1003\",\"tw_1010\"]}]",
  "trend": "{\"emerging\":[\"长链推理\"],\"fading\":[\"上一代模型对比\"]}",
  "cited": "tw_1001,tw_1003,tw_1010",
  "covered_until": "2026-06-29T06:00:00Z",
  "playbook_id": "xw-review",
  "playbook_version": "1.0.0",
  "prompt_hash": "50eac701a826f70dad06d9b3e6cd199d6f9846ff683bfc19cb2b8f521d1b77ed",
  "candidate_set_hash": "5f08779df2d867b834d023108bf7b2747640c5324f3ae5273da010adbf9cc109",
  "candidate_ids": "tw_1001,tw_1003,tw_1010",
  "model_name": null,
  "model_version": null
}
```

Success response:

- `success=true`
- `data.subject_id=s_ai`
- `data.version=8`

Conflict response:

```json
{
  "success": false,
  "error_type": "conflict",
  "error": "版本冲突，请用最新版本重算",
  "latest_version": 9,
  "covered_until": "2026-06-29T07:30:00Z"
}
```

## Few-Shot Run

### Input Context

`xw-classify` has already written the latest AI subject matches. The current review is at version 7 and covered through `2026-06-29T00:00:00Z`. New matches include `tw_1001`, `tw_1003`, and `tw_1010`.

### Authoritative Candidate Set

Call `get_subject_candidate_set(subject_id="s_ai", time_axis="review")` and copy `candidate_ids=["tw_1001","tw_1003","tw_1010"]` plus `candidate_set_hash`. Existing `get_subject_feed` calls may still provide text and citation context, but they are not the hash source.

### Write

```json
{
  "subject_id": "s_ai",
  "prev_version": 7,
  "sections": "[{\"title\":\"模型能力演进\",\"body\":\"自上轮以来，o5 推理模型成为焦点，长链推理为主要卖点。\",\"cited_tweet_ids\":[\"tw_1001\"]},{\"title\":\"社区反应\",\"body\":\"社区围绕基准对比展开讨论。\",\"cited_tweet_ids\":[\"tw_1003\",\"tw_1010\"]}]",
  "trend": "{\"emerging\":[\"长链推理\"],\"fading\":[\"上一代模型对比\"]}",
  "cited": "tw_1001,tw_1003,tw_1010",
  "covered_until": "2026-06-29T06:00:00Z",
  "playbook_id": "xw-review",
  "playbook_version": "1.0.0",
  "prompt_hash": "50eac701a826f70dad06d9b3e6cd199d6f9846ff683bfc19cb2b8f521d1b77ed",
  "candidate_set_hash": "5f08779df2d867b834d023108bf7b2747640c5324f3ae5273da010adbf9cc109",
  "candidate_ids": "tw_1001,tw_1003,tw_1010",
  "model_name": null,
  "model_version": null
}
```

### Expected Result

- `success=true`
- `data.subject_id=s_ai`
- `data.version=8`

### Conflict Result

```json
{
  "success": false,
  "error_type": "conflict",
  "error": "版本冲突，请用最新版本重算",
  "latest_version": 9,
  "covered_until": "2026-06-29T07:30:00Z"
}
```

## Failure And Retry Rules

- W2 conflict retry is capped at one retry.
- On conflict, use returned `latest_version` and `covered_until` as hints, then call `get_subject_review` and `get_subject_feed(since=covered_until)`.
- Before retrying a conflict, call `get_subject_candidate_set(subject_id, time_axis="review")` again and recompute `prompt_hash` from `.claude/skills/xw-review/SKILL.md`; do not reuse the old candidate ids, old `candidate_set_hash`, or old `prompt_hash`.
- Recompute cumulatively from the latest review and retry with `prev_version=latest_version`.
- If the retry also conflicts, give up and report the conflict.
- Section body over 4000 characters: shrink and rewrite the section, then retry once.
- Citation ids outside the known subject match set: drop or recompute unsupported citations, then retry once.
- Provenance assembly failure, such as `get_subject_candidate_set` returning an error or being unable to read `.claude/skills/xw-review/SKILL.md`, is a skill-side degradation path: write the same review without the seven provenance arguments and warn that provenance was not produced.
- Service-side `validation` caused by a `candidate_set_hash` mismatch is not a degradation path. Report the service diagnostic, including the system recomputed count, hash prefix, and sample ids when present; do not silently retry by dropping provenance.
- `not_found` or permission errors: stop the round and report the blocking error.
- No new matches: do not write a new review version.
