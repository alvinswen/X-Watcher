"""Extract default_prompt from persisted MCP result."""
import json
import sys
from pathlib import Path

src = Path(sys.argv[1])
out = Path(sys.argv[2])
raw = src.read_text(encoding="utf-8")
outer = json.loads(raw)
inner = json.loads(outer["result"])
data = inner["data"]
out.write_text(data["default_prompt"], encoding="utf-8")
print(f"WROTE {out}: {out.stat().st_size} bytes")
