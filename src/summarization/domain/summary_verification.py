"""摘要/翻译入库前的确定性验证门（save 层）。

纯函数，不依赖数据库；供 ``save_summaries`` 在写库前逐条校验，
校验未过的项**不入库**而是计入 errors —— 替代此前"坏译文静默入库"的行为。

规则源自 ``/scrape-and-translate`` 与项目 CLAUDE.md 的翻译约定，
但**长度比经实测重新校准**（见下方常量注释）。

长度基准统一为"剥 URL 后正文字符数"（已用户确认），
英文原文与中译文都按同一口径计算后再求比值。
"""

import re

from src.summarization.domain.language_utils import chinese_char_ratio

# 长度比 = 中译文正文字符数 / 英文原文正文字符数（均剥 URL、去空白后计）。
# ⚠️ 中文信息密度高于英文，忠实英译中的字符比通常落在 ~0.30-0.50
#    （实测样本约 0.33），因此 slash-command 字面的 "60%-120%" 当硬门会
#    误杀几乎所有合法翻译。此处是"截断 / 失控兜底带"而非字面阈值，
#    需要时改这两个常量即可一行调参。
LENGTH_RATIO_MIN = 0.25   # 低于此判为疑似截断
LENGTH_RATIO_MAX = 1.50   # 高于此判为疑似失控 / 过度生成

# 原文正文短于此阈值时，跳过"长度比"与"缺译"检查，避免在极短推文上产生噪声。
MIN_BASIS_LEN = 20

_URL_RE = re.compile(r"https?://\S+")
_ELLIPSIS_SUFFIXES = ("…", "...")


def _content_len(text: str | None) -> int:
    """正文字符数：剥 URL、去所有空白后的字符长度。"""
    if not text:
        return 0
    return len(re.sub(r"\s", "", _URL_RE.sub("", text)))


def _ends_with_ellipsis(text: str | None) -> bool:
    """是否以省略号结尾（中文 … 或英文 ...，忽略尾随空白）。"""
    if not text:
        return False
    stripped = text.rstrip()
    return any(stripped.endswith(suffix) for suffix in _ELLIPSIS_SUFFIXES)


def original_basis(
    tweet_text: str | None,
    referenced_text: str | None,
    reference_type: str | None,
) -> str:
    """根据推文类型确定"译文对应的原文基准"。

    - retweeted：译文≈被转推原文 → 用 referenced_text
    - quoted / replied_to：译文涵盖评论+原文 → 用 text + referenced_text
    - 其他（original / None）：用 text
    任一缺失时退化到另一可用文本。
    """
    text = tweet_text or ""
    referenced = referenced_text or ""
    if reference_type == "retweeted" and referenced.strip():
        return referenced
    if reference_type in ("quoted", "replied_to") and referenced.strip():
        return f"{text} {referenced}".strip()
    return text or referenced


def verify_translation(
    translation: str | None,
    tweet_text: str | None,
    referenced_text: str | None = None,
    reference_type: str | None = None,
) -> str | None:
    """校验一条译文是否可入库。

    Returns:
        None 表示通过；非空字符串为失败原因（写入 errors）。

    降级策略：原文基准为空时无法做原文相关校验，返回 None（放行），
    不阻断入库。
    注（CHG-046）：save_summaries 已前置"库内存在性"闸——"库内查无此推文"
    的条目在进入本函数前即被结构化拒绝，本放行分支在生产路径仅由
    "推文存在但正文与被引用文均为空"（纯媒体推文）触达。
    """
    basis = original_basis(tweet_text, referenced_text, reference_type)
    if not basis.strip():
        return None  # 原文缺失 → 降级放行

    basis_len = _content_len(basis)
    english_dominant = chinese_char_ratio(basis) < 0.5
    has_translation = bool(translation and translation.strip())

    # 规则 1：实质英文推文必须有翻译
    if english_dominant and basis_len >= MIN_BASIS_LEN and not has_translation:
        return "英文推文缺少翻译"

    # 非英文且无翻译（纯中文可为 null）→ 放行
    if not has_translation:
        return None

    # 规则 2：译文不得以省略号结尾，除非原文如此（截断的高信号）
    if _ends_with_ellipsis(translation) and not _ends_with_ellipsis(basis):
        return "译文以省略号结尾但原文未如此（疑似截断）"

    # 规则 3：长度比兜底（仅对英文主导且足够长的原文）
    if english_dominant and basis_len >= MIN_BASIS_LEN:
        ratio = _content_len(translation) / basis_len
        if ratio < LENGTH_RATIO_MIN:
            return (
                f"译文过短（长度比 {ratio:.0%} < {LENGTH_RATIO_MIN:.0%}，疑似截断）"
            )
        if ratio > LENGTH_RATIO_MAX:
            return f"译文过长（长度比 {ratio:.0%} > {LENGTH_RATIO_MAX:.0%}）"

    return None
