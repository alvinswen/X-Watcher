"""language_utils 模块的单元测试。"""

import pytest

from src.summarization.domain.language_utils import (
    chinese_char_ratio,
    is_chinese_dominant,
    is_mixed_language,
)


class TestChineseCharRatio:
    """chinese_char_ratio 函数测试。"""

    def test_empty_string(self):
        assert chinese_char_ratio("") == 0.0

    def test_none_like_empty(self):
        assert chinese_char_ratio("   ") == 0.0

    def test_pure_chinese(self):
        ratio = chinese_char_ratio("今天天气真好")
        assert ratio == pytest.approx(1.0)

    def test_pure_english(self):
        ratio = chinese_char_ratio("OpenAI released GPT-5 today")
        assert ratio == pytest.approx(0.0)

    def test_mixed_content(self):
        ratio = chinese_char_ratio("今天OpenAI发布了GPT-5")
        # 中文字符: 今天发布了 = 5, 总有效字符: 5 + len("OpenAIGPT-5") = 5+11 = 16
        assert 0.2 < ratio < 0.5

    def test_url_stripped(self):
        """URL 应被剥离，不影响占比计算。"""
        ratio = chinese_char_ratio("今天天气真好 https://example.com/very/long/path")
        assert ratio == pytest.approx(1.0)

    def test_mention_stripped(self):
        """@mentions 应被剥离。"""
        ratio = chinese_char_ratio("@elonmusk 今天天气真好")
        assert ratio == pytest.approx(1.0)

    def test_hashtag_stripped(self):
        """#hashtags 应被剥离。"""
        ratio = chinese_char_ratio("#AI 今天天气真好")
        assert ratio == pytest.approx(1.0)

    def test_only_urls_and_mentions(self):
        """只有 URL 和 @mention 的文本应返回 0.0。"""
        ratio = chinese_char_ratio("https://example.com @user #tag")
        assert ratio == 0.0

    def test_emoji_only(self):
        """纯 emoji 不是中文字符。"""
        ratio = chinese_char_ratio("🚀🎉👍")
        assert ratio == 0.0

    def test_chinese_with_emoji(self):
        """中文 + emoji 混合，emoji 算有效字符但不算中文。"""
        ratio = chinese_char_ratio("太棒了🚀")
        # 中文: 太棒了 = 3, emoji: 🚀 = 1, 总有效 = 4
        assert 0.5 < ratio < 1.0

    def test_fullwidth_punctuation(self):
        """全角标点应计为 CJK 字符。"""
        ratio = chinese_char_ratio("你好！世界？")
        assert ratio > 0.8

    def test_numbers_only(self):
        ratio = chinese_char_ratio("12345 67890")
        assert ratio == 0.0

    def test_cjk_punctuation(self):
        """CJK 标点符号（U+3000-U+303F 范围）。"""
        ratio = chinese_char_ratio("「引用原文」")
        assert ratio > 0.5


class TestIsChineseDominant:
    """is_chinese_dominant 函数测试。"""

    def test_pure_chinese(self):
        assert is_chinese_dominant("今天天气真好") is True

    def test_pure_english(self):
        assert is_chinese_dominant("OpenAI released GPT-5") is False

    def test_empty_string(self):
        assert is_chinese_dominant("") is False

    def test_threshold_boundary_above(self):
        """占比恰好 >= 0.5 时应返回 True。"""
        # "好AB" -> 中文1/有效3 = 0.33, False
        assert is_chinese_dominant("好AB") is False

    def test_threshold_boundary_exact(self):
        # "好A" -> 中文1/有效2 = 0.5, True
        assert is_chinese_dominant("好A") is True

    def test_custom_threshold(self):
        assert is_chinese_dominant("好ABC", threshold=0.2) is True
        assert is_chinese_dominant("好ABC", threshold=0.3) is False

    def test_quoted_tweet_chinese_comment_english_ref(self):
        """中文评论 + 英文引文的典型 quoted 推文。"""
        text = "太强了！\n\n[引用原文]: OpenAI announces GPT-5 with improved reasoning"
        # 中文字符较少，英文占多数 -> 混合偏英文
        assert is_chinese_dominant(text) is False

    def test_quoted_tweet_chinese_both(self):
        """中文评论 + 中文引文。"""
        text = "说得好！\n\n[引用原文]: 今天上海天气晴朗，适合出门散步"
        assert is_chinese_dominant(text) is True


class TestIsMixedLanguage:
    """is_mixed_language 函数测试。"""

    def test_pure_chinese_not_mixed(self):
        """纯中文占比 > 0.8，不算混合。"""
        assert is_mixed_language("今天天气真好啊朋友们") is False

    def test_pure_english_not_mixed(self):
        """纯英文占比 < 0.2，不算混合。"""
        assert is_mixed_language("OpenAI released GPT-5 today") is False

    def test_mixed_content(self):
        """中英混合：中文评论占一定比例。"""
        text = "这个模型的推理能力提升太大了！\n\n[引用原文]: OpenAI announces GPT-5 with improved reasoning"
        assert is_mixed_language(text) is True

    def test_empty_string(self):
        assert is_mixed_language("") is False

    def test_slight_chinese_in_english(self):
        """少量中文在大段英文中，占比 < 0.2。"""
        text = "好 This is a very long English tweet about technology and AI"
        assert is_mixed_language(text) is False

    def test_custom_bounds(self):
        """自定义边界。"""
        # "好AB" -> ratio ≈ 0.33
        assert is_mixed_language("好AB", chinese_lower=0.3, chinese_upper=0.4) is True
        assert is_mixed_language("好AB", chinese_lower=0.4, chinese_upper=0.8) is False
