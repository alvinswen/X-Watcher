"""MCP 安全模块：审计日志 + Action Guard。

审计日志：记录所有写操作的调用信息，用于事后追溯。
Action Guard：通过环境变量控制每个工具允许的 action 列表，用于事前拦截。
"""

import logging
import os
from datetime import datetime, timezone

from src.mcp.auth import get_user_name
from src.mcp.helpers import error_response

audit_logger = logging.getLogger("xwatcher.audit")
security_logger = logging.getLogger("xwatcher.security")

# 工具名 → 环境变量名映射
_GUARD_ENV_MAP: dict[str, str] = {
    "manage_follows": "MCP_FOLLOWS_ALLOWED_ACTIONS",
    "trigger_scrape": "MCP_TRIGGER_SCRAPE_ALLOWED_ACTIONS",
    "trigger_backfill": "MCP_TRIGGER_BACKFILL_ALLOWED_ACTIONS",
}

# 进程级缓存：工具名 → 允许的 action 集合（None 表示全部允许）
_guard_cache: dict[str, set[str] | None] = {}


def _get_allowed_actions(tool_name: str) -> set[str] | None:
    """获取工具允许的 action 列表（带缓存）。"""
    if tool_name in _guard_cache:
        return _guard_cache[tool_name]

    env_var = _GUARD_ENV_MAP.get(tool_name)
    if not env_var:
        _guard_cache[tool_name] = None
        return None

    value = os.environ.get(env_var)
    if not value:
        _guard_cache[tool_name] = None
        return None

    allowed = {a.strip().lower() for a in value.split(",") if a.strip()}
    _guard_cache[tool_name] = allowed
    return allowed


def check_action_guard(tool_name: str, action: str) -> str | None:
    """检查 action 是否被允许。

    Returns:
        None 表示允许；非 None 返回错误 JSON 字符串。
    """
    allowed = _get_allowed_actions(tool_name)
    if allowed is None:
        return None
    if action.lower() in allowed:
        return None
    return error_response(
        f"操作被拒绝: {tool_name}.{action} 不在允许列表 {sorted(allowed)} 中",
        "permission",
    )


def check_scrape_guard() -> str | None:
    """检查 trigger_scrape 是否被允许。

    环境变量 MCP_SCRAPE_ENABLED 控制，默认 true。

    Returns:
        None 表示允许；非 None 返回错误 JSON 字符串。
    """
    value = os.environ.get("MCP_SCRAPE_ENABLED", "true").lower()
    if value in ("true", "1", "yes"):
        return None
    return error_response(
        "操作被拒绝: trigger_scrape 已被禁用 (MCP_SCRAPE_ENABLED=false)",
        "permission",
    )


def audit_log(
    tool: str,
    action: str,
    *,
    params: dict | None = None,
    result: str = "success",
    error: str | None = None,
    source: str = "mcp",
    user: str | None = None,
) -> None:
    """记录审计日志。

    Args:
        tool: 工具/端点名称
        action: 操作类型
        params: 操作参数
        result: 操作结果（"success" 或 "failure"）
        error: 错误信息
        source: 来源（"mcp" 或 "api"）
        user: 用户名（None 时自动获取）
    """
    if user is None:
        user = get_user_name()
    now = datetime.now(timezone.utc)
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


def log_action_guard_config() -> None:
    """启动时打印当前 guard 配置。"""
    lines = []
    for tool_name in _GUARD_ENV_MAP:
        allowed = _get_allowed_actions(tool_name)
        if allowed is None:
            lines.append(f"  {tool_name}: 全部允许")
        else:
            lines.append(f"  {tool_name}: {sorted(allowed)}")

    scrape_enabled = os.environ.get("MCP_SCRAPE_ENABLED", "true").lower()
    scrape_status = "允许" if scrape_enabled in ("true", "1", "yes") else "禁用"
    lines.append(f"  scrape/backfill 整体开关 (MCP_SCRAPE_ENABLED): {scrape_status}")

    security_logger.info("Action Guard 配置:\n%s", "\n".join(lines))
