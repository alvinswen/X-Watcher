"""主题综述 Step 3 自检:
1. observations.source_tweet_ids ⊆ allowed_tweet_ids
2. 长推 ∩ 主题相关 - 已引用 = 漏报集 (供主对话判断是否需要补观点或合理跳过)

跑法: python scripts/selfcheck_review.py <draft.md> <prompt-result-json.txt>
"""
import json
import re
import sys
from pathlib import Path


KEYWORDS = {
    "harness", "context", "compaction", "tool", "skill", "mcp", "subagent", "sub-agent",
    "sandbox", "isolated", "permission", "runtime", "primitive", "loop", "iteration",
    "multi-agent", "multi agent", "manager-worker", "orchestrat", "plugin", "extension",
    "marketplace", "observability", "trace", "audit", "claude code", "openclaw", "codex",
    "checkpoint", "resume", "snapshot", "eval", "benchmark",
}


def main() -> None:
    draft_path = Path(sys.argv[1])
    prompt_result_path = Path(sys.argv[2])

    draft = draft_path.read_text(encoding="utf-8")

    # 1. 解析 observations 块
    obs_match = re.search(r"```observations\s*\n(.+?)\n```", draft, re.DOTALL)
    if not obs_match:
        print("ERROR: observations 代码块未找到")
        sys.exit(1)
    obs = json.loads(obs_match.group(1))
    cited_ids = set()
    for ob in obs["observations"]:
        for tid in ob["source_tweet_ids"]:
            cited_ids.add(tid)
    print(f"观点数: {len(obs['observations'])}, 唯一 source_tweet_ids: {len(cited_ids)}")

    # 2. 加载 allowed_tweet_ids
    raw = prompt_result_path.read_text(encoding="utf-8")
    data = json.loads(json.loads(raw)["result"])["data"]
    allowed = set(data["allowed_tweet_ids"])
    prompt_text = data["default_prompt"]
    print(f"allowed_tweet_ids: {len(allowed)}")

    # 3. 检查 source_tweet_ids ⊆ allowed
    illegal = cited_ids - allowed
    if illegal:
        print(f"❌ 非法引用 (不在 allowed 里): {illegal}")
        sys.exit(2)
    else:
        print(f"✅ 全部 source_tweet_ids 都在 allowed_tweet_ids 内")

    # 4. 解析 prompt 中每条推文的 author + body 长度
    tweet_pat = re.compile(
        r"^tweet_id=(?P<tid>\d+) \| @(?P<author>[A-Za-z0-9_]+) \| "
        r"\[(?P<created_at>[^\]]+)\] (?P<text>.+?)$",
        re.MULTILINE,
    )
    ref_pat = re.compile(r"^  ↪ via (?:@(?P<refauth>[A-Za-z0-9_]+)|via): (?P<reftext>.+?)$",
                         re.MULTILINE)

    tweets = []
    matches = list(tweet_pat.finditer(prompt_text))
    for i, m in enumerate(matches):
        next_pos = matches[i + 1].start() if i + 1 < len(matches) else len(prompt_text)
        between = prompt_text[m.end():next_pos]
        ref_m = ref_pat.search(between)
        ref_text = ref_m.group("reftext") if ref_m else ""
        body = m.group("text") + ref_text
        tweets.append({
            "tid": m.group("tid"),
            "author": m.group("author"),
            "body": body,
            "body_len": len(body),
        })

    # 5. 长推 ∩ 主题相关但未引用 = 漏报集
    long_relevant = []
    for t in tweets:
        if t["body_len"] < 300:
            continue
        body_lower = t["body"].lower()
        if any(kw in body_lower for kw in KEYWORDS):
            long_relevant.append(t)

    missed = [t for t in long_relevant if t["tid"] not in cited_ids]
    print(f"\n长推 ∩ 主题相关: {len(long_relevant)}")
    print(f"已引用: {len(long_relevant) - len(missed)}")
    print(f"漏报集: {len(missed)} 条")

    # 按 body_len 倒序输出 top 30 漏报,供主对话判断
    missed.sort(key=lambda x: -x["body_len"])
    print(f"\n=== 漏报 top 20 (按 body 长度倒序) ===")
    for t in missed[:20]:
        preview = t["body"][:200].replace("\n", " ")
        print(f"  [{t['tid']}] @{t['author']} body={t['body_len']}")
        print(f"    {preview}...")
        print()


if __name__ == "__main__":
    main()
