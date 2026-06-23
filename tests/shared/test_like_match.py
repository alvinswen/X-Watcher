"""src.shared.like_match 复刻 SQL col.ilike("%kw%")(对齐 PG)。"""
from src.shared.like_match import ilike_contains, like_to_regex


def test_basic_case_insensitive():
    assert ilike_contains("Hello GPT World", "gpt") is True
    assert ilike_contains("nothing here", "gpt") is False


def test_none_haystack():
    assert ilike_contains(None, "x") is False


def test_wildcard_underscore():
    # _ = 任意单字符(SQL LIKE)
    assert ilike_contains("abc", "a_c") is True
    assert ilike_contains("axc", "a_c") is True
    assert ilike_contains("ac", "a_c") is False


def test_wildcard_percent():
    # % = 任意串(可空)
    assert ilike_contains("axxxc", "a%c") is True
    assert ilike_contains("ac", "a%c") is True


def test_regex_specials_literal():
    # regex 特殊字符字面化(. 非通配,只有 %/_ 是 LIKE 通配)
    assert ilike_contains("a.b", "a.b") is True
    assert ilike_contains("aXb", "a.b") is False


def test_like_to_regex_shape():
    assert like_to_regex("a%b_c") == r"a.*b.c"
