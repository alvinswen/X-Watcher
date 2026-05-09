"""分析 default_prompt 内容:抽长推 + 标注关键词命中,生成 candidate brief.

跑法: python scripts/analyze_review_candidates.py <prompt.txt> <out.md>

按 harness engineering 严定义筛选:
  人/agent 与 LLM 之间那一层的工程实践——上下文管理、工具/技能设计、
  沙箱、运行时原语、多 agent 编排、插件治理、可观测性。
"""
import re
import sys
from pathlib import Path
from collections import defaultdict


KEYWORDS = {
    "harness": ["harness", "agent harness"],
    "context": ["context", "context engineering", "context window", "context management",
                "compaction", "memory"],
    "tool": ["tool", "skill", "skills", "mcp", "mcp server", "subagent", "sub-agent"],
    "sandbox": ["sandbox", "isolated", "container", "permission", "dangerous"],
    "runtime": ["runtime", "primitive", "loop", "iteration"],
    "multi_agent": ["multi-agent", "multi agent", "manager-worker", "swarm", "orchestrat"],
    "plugin": ["plugin", "extension", "marketplace"],
    "observability": ["observability", "trace", "log", "audit"],
    "claude_code": ["claude code", "openclaw", "codex", "cursor", "windsurf", "amp", "cline", "aider"],
    "checkpoint": ["checkpoint", "resume", "snapshot", "state", "persist"],
    "eval": ["eval", "benchmark", "test"],
    "model_arch": ["model", "llm", "anthropic", "openai", "gpt", "claude", "opus", "sonnet"],
    # 排除项(只是辅助标注,不主动剔除)
    "exclude_signal": ["politics", "election", "president", "trump", "biden"],
}


def categorize(text: str) -> set[str]:
    text_lower = text.lower()
    hits = set()
    for cat, kws in KEYWORDS.items():
        for kw in kws:
            if kw in text_lower:
                hits.add(cat)
                break
    return hits


def main() -> None:
    src = Path(sys.argv[1])
    out = Path(sys.argv[2])

    raw = src.read_text(encoding="utf-8")

    # 解析每条推文行: tweet_id=X | @author | [time] text  (后跟可选 ↪ via line)
    # 用正则按 tweet_id= 锚点切分
    tweet_pat = re.compile(
        r"^tweet_id=(?P<tid>\d+) \| @(?P<author>[A-Za-z0-9_]+) \| "
        r"\[(?P<created_at>[^\]]+)\] (?P<text>.+?)$",
        re.MULTILINE,
    )
    ref_pat = re.compile(r"^  ↪ via (?:@(?P<refauth>[A-Za-z0-9_]+)|via): (?P<reftext>.+?)$",
                         re.MULTILINE)

    tweets = []
    matches = list(tweet_pat.finditer(raw))
    for i, m in enumerate(matches):
        tid = m.group("tid")
        author = m.group("author")
        text = m.group("text")
        # 看下一个 tweet 起始位置之间是否有 ref line
        next_pos = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        between = raw[m.end():next_pos]
        ref_m = ref_pat.search(between)
        ref_author = ref_m.group("refauth") if ref_m and ref_m.group("refauth") else None
        ref_text = ref_m.group("reftext") if ref_m else None
        body = text + (("\n" + ref_text) if ref_text else "")
        cats = categorize(body)
        tweets.append({
            "tid": tid,
            "author": author,
            "created_at": m.group("created_at"),
            "text": text,
            "ref_author": ref_author,
            "ref_text": ref_text,
            "body_len": len(body),
            "text_len": len(text),
            "ref_len": len(ref_text) if ref_text else 0,
            "categories": cats,
        })

    # 长推 (body ≥ 300) + 关键词命中
    long_relevant = [t for t in tweets if t["body_len"] >= 300 and (t["categories"] - {"exclude_signal"})]
    long_relevant.sort(key=lambda x: -x["body_len"])

    # 短推但关键词强命中(≥3 类别)
    short_strong = [t for t in tweets if t["body_len"] < 300 and len(t["categories"] - {"exclude_signal"}) >= 3]

    # 长推但与主题弱相关(0 类别命中) — 仅供查漏
    long_offtopic = [t for t in tweets if t["body_len"] >= 300 and not (t["categories"] - {"exclude_signal"})]
    long_offtopic.sort(key=lambda x: -x["body_len"])

    by_author = defaultdict(list)
    for t in tweets:
        by_author[t["author"]].append(t)

    lines = []
    lines.append("# Topic Review Candidate Brief — harness engineering")
    lines.append(f"")
    lines.append(f"- 入选 prompt 总推文: {len(tweets)}")
    lines.append(f"- 长推(≥300 字符 body): {sum(1 for t in tweets if t['body_len'] >= 300)}")
    lines.append(f"- 长推 + 主题相关: **{len(long_relevant)}**")
    lines.append(f"- 短推但关键词强命中(≥3 类别): {len(short_strong)}")
    lines.append(f"- 长推但 0 关键词命中: {len(long_offtopic)} (查漏用)")
    lines.append(f"- author 数: {len(by_author)}")
    lines.append(f"")

    lines.append("## Author 分布(top 15)")
    lines.append(f"")
    by_author_sorted = sorted(by_author.items(), key=lambda kv: -len(kv[1]))
    for author, ts in by_author_sorted[:15]:
        long_ct = sum(1 for t in ts if t["body_len"] >= 300)
        rel_ct = sum(1 for t in ts if t["body_len"] >= 300 and (t["categories"] - {"exclude_signal"}))
        lines.append(f"- @{author}: {len(ts)} 条 (长推 {long_ct}, 长推 ∩ 相关 {rel_ct})")
    lines.append(f"")

    lines.append("## 长推 ∩ 主题相关 (按 body 长度倒序)")
    lines.append(f"")
    for t in long_relevant:
        cats_label = ", ".join(sorted(t["categories"] - {"exclude_signal"}))
        ref_info = f" ↪@{t['ref_author']}" if t["ref_author"] else ""
        lines.append(f"### [{t['tid']}] @{t['author']}{ref_info} · body={t['body_len']} · [{cats_label}]")
        lines.append(f"")
        lines.append(f"_{t['created_at'][:19]}_  ")
        lines.append(f"")
        if t["ref_text"]:
            lines.append(f"**外壳**: {t['text']}")
            lines.append(f"")
            lines.append(f"**本体** (@{t['ref_author']}): {t['ref_text']}")
        else:
            lines.append(f"{t['text']}")
        lines.append(f"")
        lines.append(f"---")
        lines.append(f"")

    lines.append("## 长推 0 关键词命中 (查漏)")
    lines.append(f"")
    for t in long_offtopic[:20]:
        ref_info = f" ↪@{t['ref_author']}" if t["ref_author"] else ""
        body_preview = (t["ref_text"] or t["text"])[:200]
        lines.append(f"- [{t['tid']}] @{t['author']}{ref_info} body={t['body_len']}: {body_preview}…")
    lines.append(f"")

    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"WROTE {out}: {out.stat().st_size} bytes")
    print(f"  长推 ∩ 相关: {len(long_relevant)}")
    print(f"  短推强命中: {len(short_strong)}")
    print(f"  长推查漏: {len(long_offtopic)}")


if __name__ == "__main__":
    main()
