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
    "manage_topic": "MCP_TOPIC_ALLOWED_ACTIONS",
    "manage_topic_accounts": "MCP_TOPIC_ACCOUNTS_ALLOWED_ACTIONS",
    "manage_follows": "MCP_FOLLOWS_ALLOWED_ACTIONS",
    "manage_scheduler": "MCP_SCHEDULER_ALLOWED_ACTIONS",
    "batch_summarize": "MCP_SUMMARIZE_ALLOWED_ACTIONS",
    "get_topic_summary": "MCP_TOPIC_SUMMARY_ALLOWED_ACTIONS",
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
    """记录审计日志（文件 + 数据库双写）。

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

    # 在线程池中持久化到数据库（fire-and-forget，不阻塞事件循环）
    import asyncio

    try:
        loop = asyncio.get_running_loop()
        loop.run_in_executor(
            None, _persist_audit_log, tool, action, user, params, result, error, source, now,
        )
    except RuntimeError:
        # 没有运行中的事件循环（同步调用场景），直接同步写入
        _persist_audit_log(tool, action, user, params, result, error, source, now)


def _persist_audit_log(
    tool: str,
    action: str,
    user: str,
    params: dict | None,
    result: str,
    error: str | None,
    source: str,
    timestamp: datetime,
) -> None:
    """将审计日志持久化到数据库（静默失败）。"""
    from src.data_layer.provider import is_file_mode

    if is_file_mode():
        # file 模式:审计仅文件 logger(audit_log 主函数已写),不写 pg(owner 定 accept-no-persist)
        return
    try:
        import json

        from sqlalchemy.orm import Session as SyncSession

        from src.database.models import AuditLog, get_engine

        engine = get_engine()
        with SyncSession(engine) as session:
            entry = AuditLog(
                timestamp=timestamp.replace(tzinfo=None),
                tool=tool,
                action=action,
                user=user,
                params_json=json.dumps(params, ensure_ascii=False, default=str) if params else None,
                result=result,
                error=error,
                source=source,
            )
            session.add(entry)
            session.commit()
    except Exception as e:
        audit_logger.debug(f"审计日志 DB 持久化失败（不影响功能）: {e}")


def log_action_guard_config() -> None:
    """启动时打印当前 guard 配置。"""
    lines = []
    for tool_name, env_var in _GUARD_ENV_MAP.items():
        allowed = _get_allowed_actions(tool_name)
        if allowed is None:
            lines.append(f"  {tool_name}: 全部允许")
        else:
            lines.append(f"  {tool_name}: {sorted(allowed)}")

    scrape_enabled = os.environ.get("MCP_SCRAPE_ENABLED", "true").lower()
    scrape_status = "允许" if scrape_enabled in ("true", "1", "yes") else "禁用"
    lines.append(f"  trigger_scrape: {scrape_status}")

    security_logger.info("Action Guard 配置:\n%s", "\n".join(lines))
