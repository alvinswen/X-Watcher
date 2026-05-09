"""Extract summary brief from get_topic_tweets_for_summary persisted file."""
import json
import sys
from pathlib import Path

src = Path(sys.argv[1])
out = Path(sys.argv[2])

raw = src.read_text(encoding="utf-8")
outer = json.loads(raw)
inner = json.loads(outer["result"])
data = inner["data"]
print("data keys:", list(data.keys()))
# Some payloads put tweets under different keys; try common variants
tweets = data.get("tweets") or data.get("tweet_list") or data.get("items") or []
if not tweets:
    print("No tweets array; full data preview:")
    for k, v in data.items():
        if isinstance(v, str):
            print(f"  {k}: {v[:120]!r}{'...' if len(v) > 120 else ''}")
        else:
            print(f"  {k}: {type(v).__name__} {v if not isinstance(v, (list, dict)) else f'(len={len(v)})'}")
    sys.exit(2)

# Group by author
by_author = {}
for t in tweets:
    u = t.get("author_username", "?")
    by_author.setdefault(u, []).append(t)

lines = []
lines.append(f"# 主题摘要素材")
lines.append(f"")
lines.append(f"- topic: {data['topic_name']}")
lines.append(f"- coverage: {data['coverage_period']}")
lines.append(f"- accounts: {data['account_count']}, tweets: {data['tweet_count']}")
lines.append(f"")
lines.append(f"## 推文清单（按账号分组）")
lines.append(f"")

for u in sorted(by_author.keys(), key=lambda x: -len(by_author[x])):
    ts = by_author[u]
    if not ts:
        continue
    name = ts[0].get("author_display_name", u)
    lines.append(f"### {name} (@{u}) — {len(ts)} 条")
    lines.append(f"")
    for t in ts:
        tid = t.get("tweet_id", "")
        ref = t.get("reference_type") or "原创"
        ref_user = t.get("referenced_tweet_author_username") or ""
        ref_label = ref if not ref_user else f"{ref}@{ref_user}"
        summary = (t.get("summary") or "").strip().replace("\n", " ")
        translation = (t.get("translation") or "").strip().replace("\n", " ")
        text = (t.get("text") or "").strip().replace("\n", " ")
        # Prefer summary; fallback to translation; fallback to text
        body = summary or translation or text
        if len(body) > 280:
            body = body[:280] + "…"
        lines.append(f"- [{tid}] ({ref_label}) {body}")
    lines.append(f"")

out.write_text("\n".join(lines), encoding="utf-8")
print(f"WROTE {out}: {out.stat().st_size} bytes, {len(tweets)} tweets, {len(by_author)} authors")
