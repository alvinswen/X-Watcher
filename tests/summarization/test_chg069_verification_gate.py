"""CHG-069 验证门口径修正回归（行为矩阵 + 可译内容谓词边界 + 口径一致性守卫）。"""

from src.summarization.domain.language_utils import (
    _CJK_PATTERN,
    _CJK_RANGES,
    chinese_char_ratio,
    content_len,
    has_translatable_content,
)
from src.summarization.domain.summary_verification import verify_translation

# ---------- 口径一致性守卫 ----------


def test_cjk_ranges_constant_matches_ratio_pattern():
    # 统一正文口径的 CJK 字符集必须与 chinese_char_ratio 的 _CJK_PATTERN 逐字同源，
    # 防止两处字符集未来各自漂移（CHG-069 问题 C 的结构性防复发）。
    assert _CJK_PATTERN.pattern == f"[{_CJK_RANGES}]"


# ---------- 行为矩阵（01-需求细化 § 4.4 关键行） ----------


def test_row2_short_english_missing_translation_rejected_a_sample():
    # A 实证样例（修前放行 → 修后拒 · 行为反转点）
    reason = verify_translation(
        None, "RT @OpenAI: Today. 10am PT.", "Today. 10am PT.", "retweeted"
    )
    assert reason is not None and "缺少翻译" in reason


def test_row3_url_glued_chinese_translation_passes_b_sample():
    # B 实证样例（修前误拒「过短 19%」→ 修后放行 · 误杀消除）
    orig = "More info at https://t.co/nJ14cKHO07, you can still start today!"
    trans = "更多信息请见 https://t.co/nJ14cKHO07，你今天仍然可以开始！"
    assert verify_translation(trans, orig, None, None) is None


def test_row4_pure_mentions_links_empty_translation_passes_c_sample():
    # C 实证样例（修前强迫写译文 → 修后留空放行）
    orig = "@AndyBeard @MFacchinello https://t.co/BlhXBWh0fV"
    assert verify_translation(None, orig, None, None) is None


def test_row5_pure_mentions_links_copied_translation_passes():
    # 宽容门（G1-3=C）：无可译内容时照抄原文为译文同样放行
    orig = "@AndyBeard @MFacchinello https://t.co/BlhXBWh0fV"
    assert verify_translation(orig, orig, None, None) is None


def test_row6_pure_emoji_empty_translation_passes():
    # 归宿不变（修前靠 20 字豁免放行，修后由「无可译内容」承载）
    assert verify_translation(None, "\U0001f525\U0001f525\U0001f525", None, None) is None


def test_row8_mixed_language_still_requires_translation_q3_sample():
    # 混排维持要求译文（G1-5=A · 占比算法零改动）
    orig = "@0xcherry 让你的同事一起来 eat，就是 at least useful"
    assert chinese_char_ratio(orig) < 0.5
    reason = verify_translation(None, orig, None, None)
    assert reason is not None and "缺少翻译" in reason


def test_row11_short_english_with_short_translation_passes():
    # 长度比 20 字豁免保留（G1-2=A）：计长 ≤19 给了非空译文即放行不卡长短
    assert content_len("ok then fine") < 20
    assert verify_translation("好", "ok then fine", None, None) is None


# ---------- 可译内容谓词边界（01 § 4.3.x 第 2 行六例 + 非拉丁组） ----------


def test_predicate_boundary_samples():
    assert has_translatable_content("@a @b https://t.co/x") is False
    assert has_translatable_content("@a huge https://t.co/x") is True
    assert has_translatable_content("\U0001f525\U0001f525\U0001f525") is False
    assert has_translatable_content("10am PT") is True
    assert has_translatable_content("2025") is False
    assert has_translatable_content("#AI #ML") is False
    assert has_translatable_content("!!! ???") is False
    assert has_translatable_content(None) is False
    assert has_translatable_content("") is False


def test_predicate_non_latin_scripts_are_translatable():
    # 广义口径（Gate 2 G2-1 PM 拍板项 · 推荐方案甲）：假名/西里尔/韩文 = 可译
    assert has_translatable_content("チェックしてください") is True
    assert has_translatable_content("Отличная модель") is True
    assert has_translatable_content("한국어 트윗") is True
    # 全角拉丁随占比口径归 CJK（已知边界 · 甲/乙两方案结论相同）
    assert has_translatable_content("Ａｗｅｓｏｍｅ") is False
