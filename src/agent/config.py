"""Nanobot Agent 配置模块。

定义 Agent 系统提示和工具注册接口。
"""

from typing import Any

# TODO: 安装 nanobot-ai
# pip install git+https://github.com/HKUDS/nanobot.git
#
# 安装后取消注释以下导入：
# from nanobot import NanoBot


# 系统提示模板
SYSTEM_PROMPT = """你是 SeriousNewsAgent，一个面向科技公司高管的智能新闻助理。

你的职责：
1. 理解用户的公司战略兴趣和新闻偏好
2. 调用合适的工具来抓取、分析和处理新闻
3. 提供简洁、有价值的新闻摘要

请使用中文与用户交流。
"""


def get_system_prompt() -> str:
    """获取 Agent 系统提示。

    Returns:
        str: 系统提示内容
    """
    return SYSTEM_PROMPT


# 工具函数注册表
# 格式: {"tool_name": tool_function}
_tools: dict[str, Any] = {}


def register_tool(name: str, func: Any) -> None:
    """注册工具函数到 Agent。

    Args:
        name: 工具名称
        func: 工具函数
    """
    _tools[name] = func


def get_registered_tools() -> dict[str, Any]:
    """获取已注册的工具函数。

    Returns:
        dict: 工具函数字典
    """
    return _tools.copy()


def create_agent():
    """创建并配置 Nanobot Agent 实例。

    TODO: 实现 Nanobot 集成

    Returns:
        Agent 实例
    """
    # TODO: 实现 Nanobot Agent 创建逻辑
    # agent = NanoBot(
    #     system_prompt=SYSTEM_PROMPT,
    #     llm_backend="minimax",  # 使用 MiniMax M2.1
    # )
    #
    # # 注册工具
    # for name, func in _tools.items():
    #     agent.register_tool(name, func)
    #
    # return agent

    raise NotImplementedError(
        "Nanobot Agent 集成待实现。"
        "请先安装 nanobot-ai: pip install git+https://github.com/HKUDS/nanobot.git"
    )
