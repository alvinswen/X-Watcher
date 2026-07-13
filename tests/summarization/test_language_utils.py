"""language_utils 模块的单元测试。"""

import pytest

from src.summarization.domain.language_utils import chinese_char_ratio


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

