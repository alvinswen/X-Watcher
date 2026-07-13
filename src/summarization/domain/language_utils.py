"""语言检测工具模块。

基于 CJK Unicode 字符占比判断推文内容的主要语言，
用于翻译指令和短推文阈值的自适应。
"""

import re

# CJK 字符正则：覆盖中日韩统一表意文字及常用标点
_CJK_PATTERN = re.compile(
    r"[\u4e00-\u9fff"  # CJK Unified Ideographs
    r"\u3400-\u4dbf"  # CJK Unified Ideographs Extension A
    r"\uf900-\ufaff"  # CJK Compatibility Ideographs
    r"\u3000-\u303f"  # CJK Symbols and Punctuation
    r"\uff01-\uff60]"  # Fullwidth Forms
)

# 需要剥离的语言无关内容：URL、@mentions、#hashtags
_NOISE_PATTERN = re.compile(r"https?://\S+|@\w+|#\w+")


def chinese_char_ratio(text: str) -> float:
    """计算文本中中文字符的占比。

    先剥离 URL、@mentions、#hashtags 等语言无关内容，
    再统计 CJK 字符占有效字符（非空白）的比例。

    Args:
        text: 输入文本。

    Returns:
        中文字符占比，0.0 ~ 1.0。空字符串返回 0.0。
    """
    if not text:
        return 0.0
    stripped = _NOISE_PATTERN.sub("", text).strip()
    if not stripped:
        return 0.0
    chinese_chars = len(_CJK_PATTERN.findall(stripped))
    meaningful_chars = len(re.sub(r"\s", "", stripped))
    if meaningful_chars == 0:
        return 0.0
    return chinese_chars / meaningful_chars

