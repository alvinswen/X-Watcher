from datetime import datetime, timezone


class _FakeArticleOrm:
    tweet_id = "555"
    title = "T"
    preview_text = "p"
    cover_image_url = None
    content = "body"
    content_html = "<p>body</p>"
    author_username = "carol"
    fetched_at = datetime(2030, 1, 1, 9, 0, tzinfo=timezone.utc)
    db_created_at = datetime(2030, 1, 1, tzinfo=timezone.utc)


def test_article_to_domain_naive():
    from src.data_layer.migration.article import _to_domain
    d = _to_domain(_FakeArticleOrm())
    assert d.tweet_id == "555" and d.author_username == "carol"
    assert d.fetched_at == datetime(2030, 1, 1, 9, 0)      # aware→naive
    assert not hasattr(d, "db_created_at")
