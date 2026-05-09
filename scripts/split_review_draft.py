"""把 draft.md 切成 content + observations.json,供 save_topic_summary 使用."""
import json
import re
import sys
from pathlib import Path

src = Path(sys.argv[1])
out_content = Path(sys.argv[2])
out_obs = Path(sys.argv[3])

raw = src.read_text(encoding="utf-8")

# 锁定 observations 代码块的起止
fence_open = re.search(r"\n```observations\s*\n", raw)
content = raw[:fence_open.start()].rstrip() + "\n"

obs_match = re.search(r"```observations\s*\n(.+?)\n```", raw, re.DOTALL)
obs_json = json.loads(obs_match.group(1))

out_content.write_text(content, encoding="utf-8")
out_obs.write_text(json.dumps(obs_json["observations"], ensure_ascii=False, indent=2), encoding="utf-8")

print(f"content: {out_content} ({len(content)} chars)")
print(f"observations: {out_obs} ({len(obs_json['observations'])} items)")
print(f"first obs: {json.dumps(obs_json['observations'][0], ensure_ascii=False)[:120]}...")
