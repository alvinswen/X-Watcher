"""MCP 契约守卫共用的文本归一（CHG-DSH-002）。

契约 = 内容，不是字节。description / docstring 按同一套规则归一后比较：
按行剥首尾空白 → 丢空行 → 行内连续空白折叠为单空格 → 行间单空格连接。
等价实现 `" ".join(value.split())`；参数 / 签名不经过本函数。
"""

from __future__ import annotations

from typing import Any

TEXT_FIELDS = ("description", "docstring")


def normalize_contract_text(value: str | None) -> str | None:
    if not isinstance(value, str):
        return value
    return " ".join(value.split())


def normalize_contract_dump(
    dump: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        name: {
            field: normalize_contract_text(value) if field in TEXT_FIELDS else value
            for field, value in fields.items()
        }
        for name, fields in dump.items()
    }
