from datetime import datetime, timezone


class _FakeSummaryOrm:
    summary_id = "uuid-1"
    tweet_id = "777"
    summary_text = "s"
    translation_text = "翻译"
    model_provider = "openai"
    model_name = "gpt-x"
    prompt_tokens = 100
    completion_tokens = 50
    total_tokens = 150
    cost_usd = 0.01
    cached = False
    is_generated_summary = True
    content_hash = "abc123"
    created_at = datetime(2030, 1, 1, 10, 0, tzinfo=timezone.utc)
    updated_at = datetime(2030, 1, 2, 11, 0, tzinfo=timezone.utc)


def test_summary_to_domain_naive():
    from src.data_layer.migration.summary import _to_domain
    d = _to_domain(_FakeSummaryOrm())
    assert d.summary_id == "uuid-1" and d.tweet_id == "777"
    assert d.created_at == datetime(2030, 1, 1, 10, 0)   # aware→naive
    assert d.updated_at == datetime(2030, 1, 2, 11, 0)
    assert d.total_tokens == 150 and d.cached is False
