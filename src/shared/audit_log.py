"""审计日志纯写入层。

本模块只负责拼装并写入审计日志，调用方必须显式提供 ``user``。
需要从 MCP 会话解析默认用户名时，应使用 ``src.mcp.security.audit_log``；
shared 层不得反向依赖 MCP 层。
"""

import logging
from datetime import UTC, datetime
from typing import Any

audit_logger = logging.getLogger("xwatcher.audit")


def audit_log(
    tool: str,
    action: str,
    *,
    params: dict[str, Any] | None = None,
    result: str = "success",
    error: str | None = None,
    source: str = "mcp",
    user: str,
) -> None:
    """记录已明确用户身份的审计日志。"""
    now = datetime.now(UTC)
    params_str = str(params) if params else ""

    msg = (
        f"AUDIT | tool={tool} | action={action} | user={user} "
        f"| result={result} | time={now.isoformat()}"
    )
    if params_str:
        msg += f" | params=({params_str})"
    if error:
        msg += f" | error={error}"

    if result == "success":
        audit_logger.info(msg)
    else:
        audit_logger.warning(msg)
