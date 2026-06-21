"""summary_verification 验证门纯函数测试。"""

from src.summarization.domain.summary_verification import (
    LENGTH_RATIO_MAX,
    LENGTH_RATIO_MIN,
    _content_len,
    _ends_with_ellipsis,
    original_basis,
    verify_translation,
)

# 真实样本（本批马斯克推文）：英文 ~170 字符 → 中译 ~56 字符，比值约 0.33
EN_ORIGINAL = (
    "People in Africa are not starving. This is a myth. The only time there "
    "is a shortage of food is when there is a war going on and the only way "
    "to solve that would be invasion!"
)
ZH_GOOD = (
    "非洲人并没有在挨饿，这是一个谬误。唯一出现粮食短缺的时候就是有战争发生"
    "之时，而解决这个问题的唯一办法就是出兵干预！"
)


# ---------- 辅助函数 ----------

def test_content_len_strips_urls_and_whitespace():
    assert _content_len("hello https://t.co/abc world") == len("helloworld")
    assert _content_len("  a b\nc ") == 3
    assert _content_len(None) == 0
    assert _content_len("") == 0


def test_ends_with_ellipsis_unicode_and_ascii():
    assert _ends_with_ellipsis("内容未完……") is True
    assert _ends_with_ellipsis("truncated...") is True
    assert _ends_with_ellipsis("完整句子。") is False
    assert _ends_with_ellipsis("ends with space …  ") is True  # 忽略尾随空白
    assert _ends_with_ellipsis(None) is False


def test_original_basis_by_reference_type():
    assert original_basis("RT prefix", "real content", "retweeted") == "real content"
    assert original_basis("我的评论", "原文", "quoted") == "我的评论 原文"
    assert original_basis("我的回复", "被回复原文", "replied_to") == "我的回复 被回复原文"
    assert original_basis("原创内容", None, "original") == "原创内容"
    # referenced 缺失时退化到 text
    assert original_basis("text only", "", "retweeted") == "text only"


# ---------- 通过场景 ----------

def test_good_english_translation_passes():
    assert verify_translation(ZH_GOOD, EN_ORIGINAL, None, None) is None


def test_pure_chinese_with_null_translation_passes():
    zh_original = "我感觉 github 现在就是 appstore 的定位了，大家都在上面找项目。"
    assert verify_translation(None, zh_original, None, None) is None


def test_missing_original_degrades_to_pass():
    # DB 查不到原文（全 None）→ 降级放行，不阻断入库
    assert verify_translation("任意译文", None, None, None) is None


def test_short_english_without_translation_skipped():
    # 极短英文（正文 < MIN_BASIS_LEN）跳过缺译检查
    assert verify_translation(None, "ok", None, None) is None


def test_translation_ellipsis_allowed_when_original_truncated():
    # 原文本身被 Twitter 截断以 … 结尾 → 译文同样结尾应放行
    truncated_en = (
        "When I was 14 years old I read every book on how to meet people and "
        "the one big takeaway was to always stay calm and collected…"
    )
    assert verify_translation("我14岁时读遍了所有教人社交的书，最大的收获就是永远保持冷静淡定……",
                              truncated_en, None, None) is None


def test_retweet_uses_referenced_text_for_basis():
    # 转推：原文基准取 referenced_text，长度比应基于它
    referenced = (
        "This is the full original tweet content that was retweeted and it is "
        "reasonably long so the ratio check applies to it properly here."
    )
    zh = "这是被转推的完整原始推文内容，相当长，因此长度比检查应正确地基于它进行。"
    assert verify_translation(zh, "RT @user:", referenced, "retweeted") is None


# ---------- 失败场景 ----------

def test_substantive_english_missing_translation_fails():
    reason = verify_translation(None, EN_ORIGINAL, None, None)
    assert reason is not None and "缺少翻译" in reason


def test_translation_trailing_ellipsis_fails_when_original_complete():
    reason = verify_translation("这是一个被截断的翻译……", EN_ORIGINAL, None, None)
    assert reason is not None and "省略号" in reason


def test_truncated_translation_too_short_fails():
    reason = verify_translation("非洲人。", EN_ORIGINAL, None, None)
    assert reason is not None and "过短" in reason
    # 比值确实低于下限
    assert "%" in reason


def test_runaway_translation_too_long_fails():
    short_en = "AI is the future of modern software work today and beyond."
    long_zh = "人工智能" * 40  # 远超原文正文长度
    reason = verify_translation(long_zh, short_en, None, None)
    assert reason is not None and "过长" in reason


# ---------- 边界 ----------

def test_ratio_constants_sane():
    assert 0 < LENGTH_RATIO_MIN < 1 < LENGTH_RATIO_MAX
