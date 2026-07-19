"""Export 服务测试。"""

import asyncio
from datetime import UTC, datetime

import pytest

from src.preference.domain.models import ScraperFollow
from src.preference.infrastructure.file_follow_repository import FileFollowStore
from src.scraper.domain.models import Article, Tweet
from src.scraper.infrastructure.file_article_repository import FileArticleStore
from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
from src.summarization.domain.models import SummaryRecord
from src.summarization.infrastructure.file_summary_repository import FileSummaryStore
from src.sync.domain.models import SyncCategory
from src.sync.services.export_service import ExportService


def _seed_file_data(root) -> None:
    """插入文件层测试数据。"""

    async def _seed() -> None:
        await FileFollowStore(root).seed([
            ScraperFollow(
                id=1,
                username="alice",
                reason="KOL",
                added_by="admin",
                added_at=datetime(2026, 1, 1, tzinfo=UTC),
                is_active=True,
            ),
            ScraperFollow(
                id=2,
                username="bob",
                reason="Developer",
                added_by="admin",
                added_at=datetime(2026, 1, 2, tzinfo=UTC),
                is_active=True,
            ),
        ])
        await FileTweetStore(root).save_tweets(
            [
                Tweet(
                    tweet_id="tw_001",
                    text="Hello from Alice",
                    created_at=datetime(2026, 2, 1, tzinfo=UTC),
                    author_username="alice",
                ),
                Tweet(
                    tweet_id="tw_002",
                    text="Hello from Bob",
                    created_at=datetime(2026, 2, 10, tzinfo=UTC),
                    author_username="bob",
                ),
            ],
            early_stop_threshold=0,
        )
        await FileSummaryStore(root).seed([
            SummaryRecord(
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
                created_at=datetime(2026, 2, 1, tzinfo=UTC),
                updated_at=datetime(2026, 2, 1, tzinfo=UTC),
            )
        ])
        await FileArticleStore(root).seed([
            Article(
                tweet_id="tw_001",
                title="Alice Article",
                content="Long article text",
                author_username="alice",
            )
        ])

    asyncio.run(_seed())


@pytest.fixture(autouse=True)
def file_export_root(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))


class TestExportService:
    def test_export_all(self, tmp_path):
        _seed_file_data(tmp_path)

        svc = ExportService()
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

    def test_export_single_category(self, tmp_path):
        _seed_file_data(tmp_path)

        svc = ExportService()
        pkg = svc.export(categories=[SyncCategory.config])

        assert pkg.metadata.categories == ["config"]
        assert "config" in pkg.data
        assert "content" not in pkg.data

    def test_export_content_with_since_filter(self, tmp_path):
        _seed_file_data(tmp_path)

        svc = ExportService()
        pkg = svc.export(
            categories=[SyncCategory.content],
            since=datetime(2026, 2, 5, tzinfo=UTC),
        )

        # 只有 bob 的推文在 2026-02-10
        assert len(pkg.data["content"]["tweets"]) == 1
        assert pkg.data["content"]["tweets"][0]["author_username"] == "bob"
        # summaries/articles 也只关联筛选后的 tweet_ids
        assert len(pkg.data["content"]["summaries"]) == 0
        assert len(pkg.data["content"]["articles"]) == 0

    def test_export_content_with_authors_filter(self, tmp_path):
        _seed_file_data(tmp_path)

        svc = ExportService()
        pkg = svc.export(
            categories=[SyncCategory.content],
            authors=["alice"],
        )

        assert len(pkg.data["content"]["tweets"]) == 1
        assert pkg.data["content"]["tweets"][0]["author_username"] == "alice"
        assert len(pkg.data["content"]["summaries"]) == 1

    def test_export_empty_database(self):
        svc = ExportService()
        pkg = svc.export()

        assert len(pkg.data["config"]["scraper_follows"]) == 0
        assert len(pkg.data["content"]["tweets"]) == 0
