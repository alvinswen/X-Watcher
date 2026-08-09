"""SQL LIKE / ILIKE 在 Python 文件层的保真复刻(对齐生产 PostgreSQL,非 SQLite)。

pg 下线文件层门面(feed/search 等)keyword 过滤复刻 `col.ilike("%kw%")`:
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


def ilike_contains(haystack: str | None, keyword: str) -> bool:
    """复刻 col.ilike(f"%{kw}%"):大小写不敏感 + kw 内 %/_ 作通配。

    无通配符时，大小写折叠后的子串判断与 contains 形式的 ILIKE 语义一致；
    含 `%`/`_` 时保留正则路径，并复用已编译的 LIKE pattern。haystack None → 不匹配。
    """
    if haystack is None:
        return False
    if "%" not in keyword and "_" not in keyword:
        return keyword.lower() in haystack.lower()
    return _compile_contains_pattern(keyword).search(haystack) is not None
