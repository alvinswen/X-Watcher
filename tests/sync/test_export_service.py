"""Export 服务测试。"""

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.database.models import Base, ScraperFollow
from src.scraper.infrastructure.article_models import ArticleOrm
from src.scraper.infrastructure.models import TweetOrm
from src.summarization.infrastructure.models import SummaryOrm
from src.sync.domain.models import SyncCategory
from src.sync.services.export_service import ExportService


def _make_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _seed_data(session: Session) -> None:
    """插入测试数据。"""
    # Config
    session.add(
        ScraperFollow(
            username="alice",
            reason="KOL",
            added_by="admin",
            added_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )
    session.add(
        ScraperFollow(
            username="bob",
            reason="Developer",
            added_by="admin",
            added_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
    )
    # Content
    session.add(
        TweetOrm(
            tweet_id="tw_001",
            text="Hello from Alice",
            created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            author_username="alice",
        )
    )
    session.add(
        TweetOrm(
            tweet_id="tw_002",
            text="Hello from Bob",
            created_at=datetime(2026, 2, 10, tzinfo=timezone.utc),
            author_username="bob",
        )
    )
    session.add(
        SummaryOrm(
            summary_id="sum_001",
            tweet_id="tw_001",
            summary_text="Alice 说 Hello",
            model_provider="openrouter",
            model_name="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.01,
            content_hash="hash1",
        )
    )
    session.add(
        ArticleOrm(
            tweet_id="tw_001",
            title="Alice Article",
            content="Long article text",
            author_username="alice",
        )
    )

    session.commit()


class TestExportService:
    def test_export_all(self):
        engine = _make_engine()
        with Session(engine) as session:
            _seed_data(session)

        with Session(engine) as session:
            svc = ExportService(session)
            pkg = svc.export(instance_id="test-server")

        assert pkg.metadata.source_instance_id == "test-server"
        assert set(pkg.metadata.categories) == {"config", "content"}

        # Config
        assert len(pkg.data["config"]["scraper_follows"]) == 2

        # Content
        assert len(pkg.data["content"]["tweets"]) == 2
        assert len(pkg.data["content"]["summaries"]) == 1
        assert len(pkg.data["content"]["articles"]) == 1

        # Counts
        assert pkg.metadata.counts["scraper_follows"] == 2
        assert pkg.metadata.counts["tweets"] == 2

    def test_export_single_category(self):
        engine = _make_engine()
        with Session(engine) as session:
            _seed_data(session)

        with Session(engine) as session:
            svc = ExportService(session)
            pkg = svc.export(categories=[SyncCategory.config])

        assert pkg.metadata.categories == ["config"]
        assert "config" in pkg.data
        assert "content" not in pkg.data

    def test_export_content_with_since_filter(self):
        engine = _make_engine()
        with Session(engine) as session:
            _seed_data(session)

        with Session(engine) as session:
            svc = ExportService(session)
            pkg = svc.export(
                categories=[SyncCategory.content],
                since=datetime(2026, 2, 5, tzinfo=timezone.utc),
            )

        # 只有 bob 的推文在 2026-02-10
        assert len(pkg.data["content"]["tweets"]) == 1
        assert pkg.data["content"]["tweets"][0]["author_username"] == "bob"
        # summaries/articles 也只关联筛选后的 tweet_ids
        assert len(pkg.data["content"]["summaries"]) == 0
        assert len(pkg.data["content"]["articles"]) == 0

    def test_export_content_with_authors_filter(self):
        engine = _make_engine()
        with Session(engine) as session:
            _seed_data(session)

        with Session(engine) as session:
            svc = ExportService(session)
            pkg = svc.export(
                categories=[SyncCategory.content],
                authors=["alice"],
            )

        assert len(pkg.data["content"]["tweets"]) == 1
        assert pkg.data["content"]["tweets"][0]["author_username"] == "alice"
        assert len(pkg.data["content"]["summaries"]) == 1

    def test_export_empty_database(self):
        engine = _make_engine()
        with Session(engine) as session:
            svc = ExportService(session)
        pkg = svc.export()

        assert len(pkg.data["config"]["scraper_follows"]) == 0
        assert len(pkg.data["content"]["tweets"]) == 0
