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


# ── CHG-069 · 统一正文口径（验证门计长/可译内容谓词的单一事实源） ──────────
# 噪声类别与 chinese_char_ratio 一致：链接 / @用户名 / #话题。
# 链接边界修正：汉字与中文标点（_CJK_RANGES 字符集）一律不算链接的一部分，
# 修正旧 `https?://\S+` 贪婪到空白、吞掉 URL 后紧贴中文的缺陷（CHG-069 问题 B）；
# 半角尾随标点仍归链接（与修前一致）。
# ⚠️ _NOISE_PATTERN / _CJK_PATTERN / chinese_char_ratio 按承诺零改动（G1-5=A）。
_CJK_RANGES = (
    r"\u4e00-\u9fff"  # CJK Unified Ideographs
    r"\u3400-\u4dbf"  # CJK Unified Ideographs Extension A
    r"\uf900-\ufaff"  # CJK Compatibility Ideographs
    r"\u3000-\u303f"  # CJK Symbols and Punctuation
    r"\uff01-\uff60"  # Fullwidth Forms
)
_CONTENT_NOISE_PATTERN = re.compile(rf"https?://[^\s{_CJK_RANGES}]+|@\w+|#\w+")


def content_len(text: str | None) -> int:
    """统一正文计长：剥链接/@用户名/#话题、去空白后的字符数（CHG-069 口径）。

    供验证门长度比检查与「可译内容」谓词共用；包3 缺译查询谓词同源复用。
    """
    if not text:
        return 0
    return len(re.sub(r"\s", "", _CONTENT_NOISE_PATTERN.sub("", text)))


def has_translatable_content(text: str | None) -> bool:
    """正文（剥链接/@用户名/#话题后）是否含可译的外文字母/单词（CHG-069 · G1-1=B）。

    口径：含任一「非 CJK 的字母类字符」即为有可译内容——拉丁/日文假名/西里尔/
    韩文等一视同仁（广义口径 · Gate 2 PM 拍板项）；emoji、纯符号、纯数字、
    纯话题标签不算。CJK 判定沿用 chinese_char_ratio 的同一字符集（全角形区
    随占比口径归 CJK，不计为可译内容）。
    """
    if not text:
        return False
    stripped = _CONTENT_NOISE_PATTERN.sub("", text)
    return any(ch.isalpha() and not _CJK_PATTERN.match(ch) for ch in stripped)
