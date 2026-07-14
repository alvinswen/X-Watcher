"""MCP 工具五件契约 golden 快照守卫。"""

from __future__ import annotations

import inspect
import json
import os
from pathlib import Path
from typing import Any

import src

_REPO_ROOT = Path.cwd().resolve()
_SRC_FILE = Path(src.__file__).resolve()
assert _SRC_FILE.is_relative_to(_REPO_ROOT / "src"), (
    f"LEAK-GUARD 失败: {_SRC_FILE} 期望位于 {_REPO_ROOT / 'src'}"
)

_GOLDEN_PATH = Path(__file__).parent / "golden" / "mcp_tool_schemas.json"


def _dump_tools() -> dict[str, dict[str, Any]]:
    from src.mcp.server import create_mcp_server

    mcp = create_mcp_server()
    return {
        name: {
            "description": tool.description,
            "parameters": tool.parameters,
            "signature": str(inspect.signature(tool.fn)),
            "docstring": inspect.getdoc(tool.fn),
        }
        for name, tool in sorted(mcp._tool_manager._tools.items())
    }


def test_mcp_tool_schemas_match_golden() -> None:
    actual = _dump_tools()
    if os.environ.get("XWATCHER_REGEN_MCP_GOLDEN") == "1":
        _GOLDEN_PATH.write_text(
            json.dumps(actual, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
            encoding="utf-8",
        )

    expected = json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))
    assert len(actual) == 32
    assert actual == expected
