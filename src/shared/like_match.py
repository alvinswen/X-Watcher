"""SQL LIKE / ILIKE 在 Python 文件层的匹配工具。

文件层门面(feed/search 等)keyword 过滤默认按字面子串匹配；
`wildcard=True` 时复刻 `col.ilike("%kw%")`:
- LIKE 通配:kw 内 `%`→任意串、`_`→任意单字符(oracle 无 ESCAPE 故 \\ 字面)。
- 大小写不敏感:re.IGNORECASE 折叠(ASCII 三方一致;非 ASCII 折叠对齐 PG ILIKE,SQLite lower()
  ASCII-only 不折叠是已知 SQLite-oracle 陷阱,跨模式测试用 ASCII keyword,非 ASCII 走 live-PG)。
"""

from __future__ import annotations

import re
from functools import lru_cache


def like_to_regex(like_pattern: str) -> str:
    """SQL LIKE pattern → 等价 regex:% → .*,_ → 任意单字符,其余字面 re.escape。"""
    out = []
    for ch in like_pattern:
        if ch == "%":
            out.append(".*")
        elif ch == "_":
            out.append(".")
        else:
            out.append(re.escape(ch))
    return "".join(out)


@lru_cache(maxsize=256)
def _compile_contains_pattern(keyword: str) -> re.Pattern[str]:
    """编译并缓存带 SQL LIKE 通配符的 contains 正则。"""
    pattern = like_to_regex(f"%{keyword}%")
    return re.compile(pattern, re.IGNORECASE | re.DOTALL)


def ilike_contains(haystack: str | None, keyword: str, *, wildcard: bool = False) -> bool:
    """大小写不敏感 contains。默认字面匹配（%/_ 为普通字符·子串快路径）；
    wildcard=True 时复刻 col.ilike(f"%{kw}%")：kw 内 % → 任意串、_ → 任意单字符（regex 慢路径）。
    haystack None → 不匹配。无通配字符时两态等价（均走快路径）。
    """
    if haystack is None:
        return False
    if not wildcard or ("%" not in keyword and "_" not in keyword):
        return keyword.lower() in haystack.lower()
    return _compile_contains_pattern(keyword).search(haystack) is not None
