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


def is_chinese_dominant(text: str, threshold: float = 0.5) -> bool:
    """判断文本是否以中文为主。

    Args:
        text: 输入文本。
        threshold: 中文字符占比达到此值即判定为中文主导。

    Returns:
        True 表示中文主导。
    """
    return chinese_char_ratio(text) >= threshold


def is_mixed_language(
    text: str,
    chinese_lower: float = 0.2,
    chinese_upper: float = 0.8,
) -> bool:
    """判断文本是否为中英文混合内容。

    中文占比在 [chinese_lower, chinese_upper] 之间视为混合。

    Args:
        text: 输入文本。
        chinese_lower: 低于此值视为纯英文。
        chinese_upper: 高于此值视为纯中文。

    Returns:
        True 表示中英文混合。
    """
    ratio = chinese_char_ratio(text)
    return chinese_lower <= ratio <= chinese_upper
