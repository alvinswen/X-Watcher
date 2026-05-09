"""把保存到 topic_summaries 的综述渲染成单文件 HTML。

读取 task_id=73(或命令行指定)的 content + metadata_json,
生成 summaries/topic-review-<slug>-<date>.html;
每个观点末尾的 `tweet_id=...` 引用渲染成可点击的 x.com 链接。

用法:
    python scripts/render_topic_review.py --task-id 73 \
        --slug harness-engineering --date 2026-05-08

不传参数时,默认渲染 latest topic_review。
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STYLE_CSS = ROOT / "summaries" / "_style.css"


REF_RE = re.compile(
    r"^- @(?P<author>[\w_]+) · (?P<date>\d{4}-\d{2}-\d{2}) · tweet_id=(?P<tid>\d+)\s*$"
)
H2_RE = re.compile(r"^## (?P<rest>.+)$")
META_HEADER_RE = re.compile(r"^\*\*(?P<label>[^：]+)：\*\*\s*(?P<value>.+)$")


def _psql(sql: str) -> str:
    out = subprocess.run(
        ["docker", "exec", "x-watcher-postgres", "psql",
         "-U", "xwatcher", "-d", "xwatcher", "-At", "-c", sql],
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return out.stdout


def fetch_summary(task_id: int) -> dict:
    """通过 docker exec psql 拉取 content + metadata_json。"""
    sql = (
        "SELECT row_to_json(t) FROM ("
        "  SELECT s.content, s.metadata_json, s.tweet_count, s.account_count,"
        "         t.created_at, t.completed_at, top.name AS topic_name "
        "  FROM topic_summaries s "
        "  JOIN topic_summary_tasks t ON s.task_id=t.id "
        "  JOIN topics top ON t.topic_id=top.id "
        f"  WHERE s.task_id={task_id}"
        ") t;"
    )
    return json.loads(_psql(sql).strip())


def fetch_tweets(tweet_ids: list[str]) -> dict[str, dict]:
    """批量查推文原文 + 翻译 + 摘要 + 引用上下文,供前端点击展开。"""
    if not tweet_ids:
        return {}
    quoted = ",".join(f"'{tid}'" for tid in tweet_ids)
    sql = (
        "SELECT json_agg(row_to_json(t)) FROM ("
        "  SELECT tw.tweet_id, tw.text, tw.created_at, tw.author_username,"
        "         tw.author_display_name, tw.reference_type,"
        "         tw.referenced_tweet_text, tw.referenced_tweet_author_username,"
        "         su.summary_text, su.translation_text"
        "  FROM tweets tw"
        "  LEFT JOIN summaries su ON tw.tweet_id = su.tweet_id"
        f"  WHERE tw.tweet_id IN ({quoted})"
        ") t;"
    )
    raw = _psql(sql).strip()
    rows = json.loads(raw) if raw else []
    return {row["tweet_id"]: row for row in (rows or [])}


def render_ref_line(m: re.Match) -> str:
    author = m["author"]
    date = m["date"]
    tid = m["tid"]
    url = f"https://x.com/{author}/status/{tid}"
    safe_author = html.escape(author)
    return (
        f'<li class="ref">'
        f'<a class="ref-link" href="{url}" target="_blank" rel="noopener">'
        f'<span class="ref-author">@{safe_author}</span>'
        f'<span class="ref-date">{date}</span>'
        f'<span class="ref-id">{tid}</span>'
        f'</a></li>'
    )


def md_to_blocks(content: str) -> list[dict]:
    """把 Markdown 拆成 (header, blocks)。

    返回结构:[
      {"kind": "title", "text": "..."},
      {"kind": "meta", "items": [(label, value), ...]},
      {"kind": "topic", "num": "1", "title": "...", "body": "...", "refs": [(@author, date, tid), ...]},
      {"kind": "section_break", "label": "综合观察"},  # ## 综合观察
      ...
    ]
    """
    lines = content.splitlines()
    out: list[dict] = []

    title = None
    meta_items: list[tuple[str, str]] = []
    i = 0
    n = len(lines)

    # Title (# ...)
    while i < n and not lines[i].strip():
        i += 1
    if i < n and lines[i].startswith("# "):
        title = lines[i][2:].strip()
        i += 1
    if title:
        out.append({"kind": "title", "text": title})

    # Pre-section meta + intro lines until first ##
    intro_lines: list[str] = []
    while i < n and not lines[i].startswith("## "):
        line = lines[i].strip()
        m = META_HEADER_RE.match(line)
        if m:
            meta_items.append((m["label"], m["value"]))
        elif line:
            intro_lines.append(line)
        i += 1
    if meta_items:
        out.append({"kind": "meta", "items": meta_items})
    if intro_lines:
        out.append({"kind": "intro", "paragraphs": intro_lines})

    # Walk topic sections
    current = None
    while i < n:
        line = lines[i]
        h2m = H2_RE.match(line)
        if h2m:
            if current:
                out.append(current)
            rest = h2m["rest"].strip()
            # Special: section break "## 综合观察"
            if rest in {"综合观察", "综合观察 (Cross-cutting)"}:
                out.append({"kind": "section_break", "label": rest})
                current = None
                i += 1
                continue
            # Try to parse "N. <title>"
            num_m = re.match(r"^(\d+)\.\s*(.+)$", rest)
            if num_m:
                current = {
                    "kind": "topic",
                    "num": num_m.group(1),
                    "title": num_m.group(2),
                    "body_lines": [],
                    "refs": [],
                }
            else:
                current = {
                    "kind": "topic",
                    "num": "",
                    "title": rest,
                    "body_lines": [],
                    "refs": [],
                }
            i += 1
            continue

        if current is None:
            i += 1
            continue

        ref_m = REF_RE.match(line)
        if ref_m:
            current["refs"].append(
                (ref_m["author"], ref_m["date"], ref_m["tid"])
            )
        elif line.strip():
            current["body_lines"].append(line.rstrip())
        i += 1

    if current:
        out.append(current)

    return out


def _format_ts(ts: str | None) -> str:
    """ISO-8601 -> 2026-05-07 21:24 (UTC)。健壮处理 None / 各种格式。"""
    if not ts:
        return ""
    # Postgres json: "2026-05-07T21:24:24+00:00"
    cleaned = ts.replace("T", " ")
    # 去掉秒以下精度,保留时区
    m = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2})", cleaned)
    head = m.group(1) if m else cleaned
    return head


def render_ref_list(refs: list[tuple[str, str, str]], tweet_data: dict[str, dict]) -> str:
    """渲染一组引用为 <ul>:每条引用是一个可展开按钮,展开后给出原文/翻译/摘要/原推链接。"""
    if not refs:
        return ""
    out = ['<ul class="ref-list">']
    for author, date, tid in refs:
        url = f"https://x.com/{author}/status/{tid}"
        td = tweet_data.get(tid) or {}
        author_dn = td.get("author_display_name") or author
        ts_full = _format_ts(td.get("created_at"))
        translation = td.get("translation_text") or ""
        original = td.get("text") or ""
        summary_text = td.get("summary_text") or ""
        ref_type = td.get("reference_type")
        quoted_author = td.get("referenced_tweet_author_username")
        quoted_text = td.get("referenced_tweet_text")

        out.append(
            f'<li class="ref">'
            f'<button class="ref-toggle" aria-expanded="false" type="button">'
            f'<span class="ref-author">@{html.escape(author)}</span>'
            f'<span class="ref-date">{html.escape(date)}</span>'
            f'<span class="ref-id">{html.escape(tid)}</span>'
            f'<span class="ref-caret">▸</span>'
            f"</button>"
        )

        # Detail panel
        out.append('<div class="ref-detail">')
        # Meta: display name + handle + full timestamp + reference type label
        meta_bits = [
            f'<strong>{html.escape(author_dn)}</strong> @{html.escape(author)}',
        ]
        if ts_full:
            meta_bits.append(html.escape(ts_full))
        if ref_type:
            type_label = {
                "retweeted": "🔁 转推",
                "quoted": "💬 引用",
                "replied_to": "↩ 回复",
            }.get(ref_type, ref_type)
            meta_bits.append(html.escape(type_label))
        out.append(f'<div class="rd-meta">{" · ".join(meta_bits)}</div>')

        # 仅保留中文翻译;若无翻译再回退到原文(中文推文 translation 可能为 null,
        # 此时直接展示原文,因为它本就是中文)
        if translation:
            out.append(
                f'<div class="rd-translation">{html.escape(translation)}</div>'
            )
        elif original and re.search(r"[一-鿿]", original):
            # 中文推文 translation 为 null,直接展示原文当作中文内容
            out.append(
                f'<div class="rd-translation">{html.escape(original)}</div>'
            )
        else:
            out.append(
                '<div class="rd-missing">(本条暂无中文翻译)</div>'
            )

        if quoted_text:
            quoted_label = (
                f'@{html.escape(quoted_author)}' if quoted_author else "(原作者未知)"
            )
            out.append(
                f'<div class="rd-quoted">'
                f'<div style="font-family: var(--font-mono); font-size: 11px;'
                f' color: var(--text-tertiary); margin-top: 4px;">'
                f'{quoted_label}</div>'
                f'{html.escape(quoted_text)}'
                f"</div>"
            )

        out.append(
            f'<div class="rd-actions">'
            f'<a href="{url}" target="_blank" rel="noopener">↗ 在 X.com 打开原推</a>'
            f"</div>"
        )
        out.append("</div>")  # .ref-detail
        out.append("</li>")
    out.append("</ul>")
    return "\n".join(out)


def render_html(summary: dict, slug: str, date_str: str, tweet_data: dict[str, dict]) -> str:
    style_css = STYLE_CSS.read_text(encoding="utf-8")
    blocks = md_to_blocks(summary["content"])
    metadata = summary.get("metadata_json") or {}
    obs_count = len(metadata.get("observations") or [])
    ref_count = sum(
        len(o.get("source_tweet_ids") or [])
        for o in (metadata.get("observations") or [])
    )

    # Identify section_break index (separates main vs 综合观察)
    section_break_idx = next(
        (idx for idx, b in enumerate(blocks) if b.get("kind") == "section_break"),
        None,
    )

    # Build title / header
    title_block = next((b for b in blocks if b.get("kind") == "title"), None)
    page_title = title_block["text"] if title_block else "Topic Review"

    # Stats
    tweet_count = summary.get("tweet_count", 0)
    account_count = summary.get("account_count", 0)
    review_window = metadata.get("review_window") or {}
    since = review_window.get("since", "?")
    until = review_window.get("until", "?")

    parts: list[str] = []
    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="zh-CN">')
    parts.append("<head>")
    parts.append('<meta charset="UTF-8">')
    parts.append(
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
    )
    parts.append(f"<title>{html.escape(page_title)}</title>")
    parts.append("<style>")
    parts.append(style_css)
    # Extra CSS for topic cards (override _style.css 默认 .topic 无 padding) and citation list
    parts.append("""
.topic { padding: 24px 28px; }
.topic-num { font-family: var(--font-mono); font-size: 11px; letter-spacing: 1.5px; color: var(--text-tertiary); text-transform: uppercase; margin-bottom: 8px; }
.topic-title { font-size: 18px; font-weight: 600; color: var(--accent); margin: 0 0 14px; line-height: 1.45; }
.topic-body { font-family: var(--font-reading); font-size: 14.5px; line-height: var(--reading-lh); letter-spacing: var(--reading-ls); color: var(--text-primary); margin: 0 0 10px; }
.ref-list { list-style: none; padding: 0; margin: 16px 0 0 0; display: flex; flex-direction: column; gap: 6px; }
.ref { font-family: var(--font-mono); font-size: 12px; }
.ref-toggle { display: flex; align-items: baseline; gap: 10px; padding: 6px 10px; border-radius: 6px; color: var(--text-secondary); background: var(--inset-bg); border: 1px solid transparent; transition: var(--transition); cursor: pointer; width: 100%; text-align: left; font-family: inherit; font-size: inherit; }
.ref-toggle:hover { background: var(--accent-bg); border-color: var(--accent); color: var(--accent); }
.ref-toggle[aria-expanded="true"] { background: var(--accent-bg); border-color: var(--accent); color: var(--accent); border-bottom-left-radius: 0; border-bottom-right-radius: 0; }
.ref-author { color: var(--accent); font-weight: 600; min-width: 140px; }
.ref-date { color: var(--text-tertiary); }
.ref-id { color: var(--text-tertiary); margin-left: auto; opacity: 0.7; font-size: 11px; }
.ref-caret { color: var(--text-tertiary); margin-left: 8px; opacity: 0.7; transition: var(--transition); }
.ref-toggle[aria-expanded="true"] .ref-caret { transform: rotate(90deg); color: var(--accent); opacity: 1; }
.ref-detail { display: none; padding: 14px 16px; background: var(--card-bg-alt); border: 1px solid var(--accent); border-top: none; border-radius: 0 0 6px 6px; font-family: var(--font-reading); font-size: 13.5px; line-height: 1.85; color: var(--text-primary); }
.ref-detail.open { display: block; }
.ref-detail .rd-meta { font-family: var(--font-mono); font-size: 11px; color: var(--text-tertiary); margin-bottom: 10px; display: flex; flex-wrap: wrap; gap: 12px; }
.ref-detail .rd-meta strong { color: var(--text-secondary); font-weight: 600; }
.ref-detail .rd-translation { color: var(--text-primary); margin: 8px 0; padding: 10px 14px; background: var(--inset-bg); border-left: 3px solid var(--accent); border-radius: 4px; }
.ref-detail .rd-translation::before { content: "中文翻译"; display: block; font-family: var(--font-mono); font-size: 10px; letter-spacing: 1.5px; color: var(--accent); margin-bottom: 6px; text-transform: uppercase; }
.ref-detail .rd-summary { color: var(--text-secondary); margin: 8px 0; padding: 10px 14px; background: var(--inset-bg); border-left: 3px solid var(--info); border-radius: 4px; font-size: 13px; }
.ref-detail .rd-summary::before { content: "中文摘要"; display: block; font-family: var(--font-mono); font-size: 10px; letter-spacing: 1.5px; color: var(--info); margin-bottom: 6px; text-transform: uppercase; }
.ref-detail .rd-original { color: var(--text-secondary); margin: 8px 0; padding: 10px 14px; background: var(--inset-bg); border-left: 3px solid var(--text-tertiary); border-radius: 4px; font-size: 13px; font-style: italic; }
.ref-detail .rd-original::before { content: "原文"; display: block; font-family: var(--font-mono); font-size: 10px; letter-spacing: 1.5px; color: var(--text-tertiary); margin-bottom: 6px; text-transform: uppercase; font-style: normal; }
.ref-detail .rd-quoted { color: var(--text-secondary); margin: 8px 0 8px 16px; padding: 10px 14px; background: var(--card-bg); border-left: 3px solid var(--text-tertiary); border-radius: 4px; font-size: 12.5px; }
.ref-detail .rd-quoted::before { content: "↪ 引用 / 转推 原帖"; display: block; font-family: var(--font-mono); font-size: 10px; letter-spacing: 1.5px; color: var(--text-tertiary); margin-bottom: 6px; text-transform: uppercase; }
.ref-detail .rd-actions { margin-top: 12px; display: flex; gap: 10px; flex-wrap: wrap; }
.ref-detail .rd-actions a { font-family: var(--font-mono); font-size: 11px; color: var(--accent); text-decoration: none; padding: 4px 10px; border: 1px solid var(--accent); border-radius: 4px; transition: var(--transition); }
.ref-detail .rd-actions a:hover { background: var(--accent); color: var(--card-bg); }
.ref-detail .rd-missing { color: var(--text-tertiary); font-style: italic; font-size: 13px; }
.review-meta { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 8px 16px; padding: 16px 20px; margin: 16px 0 28px; background: var(--inset-bg); border: 1px solid var(--border-light); border-radius: var(--card-radius); font-size: 13px; color: var(--text-secondary); }
.review-meta strong { color: var(--text-primary); margin-right: 6px; }
.intro p { color: var(--text-secondary); font-size: 14px; line-height: 1.85; margin: 0 0 8px; }
""")
    parts.append("</style>")
    parts.append("</head>")
    parts.append("<body>")
    parts.append(
        '<button class="theme-toggle" onclick="document.documentElement.classList.toggle(\'dark\')">🌓</button>'
    )
    parts.append('<div class="container">')

    # Header
    parts.append('<header class="header">')
    parts.append('<div class="brand">X-WATCHER · TOPIC REVIEW</div>')
    parts.append(f'<h1>{html.escape(page_title)}</h1>')
    parts.append(
        f'<div class="meta">{html.escape(since)} → {html.escape(until)} · '
        f'topic_id={summary.get("topic_name", "?")}</div>'
    )
    parts.append("</header>")

    # Meta items (数据范围/覆盖时段/主题来源/作者覆盖)
    meta_blocks = [b for b in blocks if b.get("kind") == "meta"]
    if meta_blocks:
        parts.append('<div class="review-meta">')
        for label, value in meta_blocks[0]["items"]:
            parts.append(
                f'<div><strong>{html.escape(label)}：</strong>'
                f'{html.escape(value)}</div>'
            )
        parts.append("</div>")

    # Stats panel
    parts.append('<div class="stats">')
    for label, val in [
        ("观点数", obs_count),
        ("引用数", ref_count),
        ("推文数", tweet_count),
        ("账号数", account_count),
    ]:
        parts.append(
            f'<div class="stat"><div class="stat-num">{val}</div>'
            f'<div class="stat-label">{label}</div></div>'
        )
    parts.append("</div>")

    # Intro paragraphs
    intro_blocks = [b for b in blocks if b.get("kind") == "intro"]
    if intro_blocks:
        parts.append('<div class="intro">')
        for p in intro_blocks[0]["paragraphs"]:
            parts.append(f"<p>{html.escape(p)}</p>")
        parts.append("</div>")

    # Topic cards (before section_break) and insight cards (after)
    topic_blocks = [b for b in blocks if b.get("kind") == "topic"]
    if section_break_idx is not None:
        before_break = []
        after_break = []
        seen_break = False
        for b in blocks:
            if b.get("kind") == "section_break":
                seen_break = True
                continue
            if b.get("kind") != "topic":
                continue
            (after_break if seen_break else before_break).append(b)
    else:
        before_break = topic_blocks
        after_break = []

    for tb in before_break:
        parts.append('<div class="topic">')
        parts.append(
            f'<div class="topic-num">观点 {html.escape(tb["num"])}</div>'
        )
        parts.append(
            f'<h2 class="topic-title">{html.escape(tb["title"])}</h2>'
        )
        if tb["body_lines"]:
            for body_line in tb["body_lines"]:
                parts.append(
                    f'<p class="topic-body">{html.escape(body_line)}</p>'
                )
        if tb["refs"]:
            parts.append(render_ref_list(tb["refs"], tweet_data))
        parts.append("</div>")

    if after_break:
        # 仅用 insights-title 作为分隔横线,卡片本体与主体观点统一(都用 .topic),
        # 避免综合观察看起来比主体观点更"重"。
        parts.append(
            '<div class="insights-title">综合观察 / cross-cutting</div>'
        )
        for tb in after_break:
            parts.append('<div class="topic">')
            parts.append(
                f'<div class="topic-num">观点 {html.escape(tb["num"])}</div>'
            )
            parts.append(
                f'<h2 class="topic-title">{html.escape(tb["title"])}</h2>'
            )
            if tb["body_lines"]:
                for body_line in tb["body_lines"]:
                    parts.append(
                        f'<p class="topic-body">{html.escape(body_line)}</p>'
                    )
            if tb["refs"]:
                parts.append(render_ref_list(tb["refs"], tweet_data))
            parts.append("</div>")

    # Footer
    parts.append('<footer class="footer">')
    parts.append(
        f'渲染时间 {summary.get("created_at", "?")} · '
        f'数据源 task_id={summary.get("task_id", "?")} · '
        f'review_kind=topic_review'
    )
    parts.append("</footer>")
    parts.append("</div>")  # container

    # Vanilla JS: 点击 .ref-toggle 切换同 li 内 .ref-detail 的 .open
    parts.append("""
<script>
(function() {
  document.querySelectorAll('.ref-toggle').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var li = btn.closest('li.ref');
      if (!li) return;
      var detail = li.querySelector('.ref-detail');
      if (!detail) return;
      var open = detail.classList.toggle('open');
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  });
})();
</script>
""")
    parts.append("</body>")
    parts.append("</html>")
    return "\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-id", type=int, default=73)
    ap.add_argument("--slug", default="harness-engineering")
    ap.add_argument("--date", default="2026-05-08")
    ap.add_argument(
        "--out",
        default=None,
        help="输出文件,默认 summaries/topic-review-<slug>-<date>.html",
    )
    args = ap.parse_args()

    summary = fetch_summary(args.task_id)
    summary["task_id"] = args.task_id
    summary["topic_name"] = summary.get("topic_name") or "?"

    # Collect all unique tweet_ids cited across observations
    metadata = summary.get("metadata_json") or {}
    cited_ids: set[str] = set()
    for o in (metadata.get("observations") or []):
        for tid in (o.get("source_tweet_ids") or []):
            cited_ids.add(str(tid))
    tweet_data = fetch_tweets(sorted(cited_ids))
    missing = sorted(cited_ids - set(tweet_data))
    print(
        f"hydrated {len(tweet_data)}/{len(cited_ids)} cited tweets"
        + (f" (missing: {missing[:3]}...)" if missing else "")
    )

    out_path = Path(args.out) if args.out else (
        ROOT / "summaries" / f"topic-review-{args.slug}-{args.date}.html"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        render_html(summary, args.slug, args.date, tweet_data),
        encoding="utf-8",
    )
    print(f"wrote {out_path} ({out_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
