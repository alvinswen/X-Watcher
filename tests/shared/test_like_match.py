"""src.shared.like_match 默认字面匹配，显式 wildcard 复刻 PG ILIKE。"""

import re

from src.shared.like_match import (
    _compile_contains_pattern,
    ilike_contains,
    like_to_regex,
)


def test_basic_case_insensitive():
    assert ilike_contains("Hello GPT World", "gpt") is True
    assert ilike_contains("nothing here", "gpt") is False


def test_none_haystack():
    assert ilike_contains(None, "x") is False


def test_wildcard_underscore():
    assert ilike_contains("abc", "a_c") is False
    assert ilike_contains("xa_cy", "a_c") is True
    assert ilike_contains("abc", "a_c", wildcard=True) is True
    assert ilike_contains("axc", "a_c", wildcard=True) is True
    assert ilike_contains("ac", "a_c", wildcard=True) is False


def test_wildcard_percent():
    assert ilike_contains("axxxc", "a%c") is False
    assert ilike_contains("xa%cy", "a%c") is True
    assert ilike_contains("axxxc", "a%c", wildcard=True) is True
    assert ilike_contains("ac", "a%c", wildcard=True) is True


def test_regex_specials_literal():
    # regex 特殊字符字面化(. 非通配,只有 %/_ 是 LIKE 通配)
    assert ilike_contains("a.b", "a.b") is True
    assert ilike_contains("aXb", "a.b") is False


def test_like_to_regex_shape():
    assert like_to_regex("a%b_c") == r"a.*b.c"


def test_plain_keyword_fast_path_matches_regex_oracle():
    haystacks = (
        "Hello GPT World",
        "Harness agents coordinate work",
        "Claude and AI",
        "马斯克发布了新消息",
        "a.b is literal text",
        "",
    )
    keywords = ("gpt", "HARNESS", "Claude", "马斯克", "a.b", "")

    for haystack in haystacks:
        for keyword in keywords:
            pattern = like_to_regex(f"%{keyword}%")
            regex_result = re.search(pattern, haystack, re.IGNORECASE | re.DOTALL) is not None
            assert ilike_contains(haystack, keyword) is regex_result


def test_wildcard_keywords_keep_regex_semantics_and_reuse_compilation():
    _compile_contains_pattern.cache_clear()

    assert ilike_contains("harness", "h_rness") is False
    assert _compile_contains_pattern.cache_info().misses == 0

    assert ilike_contains("harness", "h_rness", wildcard=True) is True
    assert ilike_contains("hrness", "h_rness", wildcard=True) is False
    assert ilike_contains("harness", "har%ss", wildcard=True) is True
    assert ilike_contains("haess", "har%ss", wildcard=True) is False

    cache_info = _compile_contains_pattern.cache_info()
    assert cache_info.misses == 2
    assert cache_info.hits == 2
