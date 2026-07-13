"""Import 服务测试。"""

import asyncio
from datetime import datetime, timezone

from src.preference.domain.models import ScraperFollow as FollowDomain
from src.preference.infrastructure.file_follow_repository import FileFollowStore
from src.scraper.domain.models import Tweet
from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
from src.summarization.domain.models import SummaryRecord
from src.summarization.infrastructure.file_summary_repository import FileSummaryStore
from src.sync.domain.models import (
    ConflictStrategy,
    ExportMetadata,
    ExportPackage,
    SyncCategory,
)
from src.sync.services.import_service import ImportService


def _make_package(data: dict, categories: list[str] | None = None) -> ExportPackage:
    if categories is None:
        categories = list(data.keys())
    return ExportPackage(
        metadata=ExportMetadata(
            exported_at=datetime(2026, 2, 24, tzinfo=timezone.utc),
            source_instance_id="test",
            categories=categories,
        ),
        data=data,
    )


def _pin_file_root(monkeypatch, root) -> None:
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(root))


def _follow_seed(username: str, reason: str, *, id: int = 1) -> FollowDomain:
    return FollowDomain(
        id=id,
        username=username,
        reason=reason,
        added_by="admin",
        added_at=datetime(2026, 1, id, tzinfo=timezone.utc),
        is_active=True,
    )


def _follow_item(username: str, reason: str, added_by: str = "admin") -> dict:
    return {
        "username": username,
        "reason": reason,
        "added_by": added_by,
        "added_at": "2026-01-01T00:00:00+00:00",
        "is_active": True,
    }


def _seed_file_roundtrip_data(root) -> None:
    async def _seed() -> None:
        await FileFollowStore(root).seed([
            FollowDomain(
                id=1,
                username="alice",
                reason="KOL",
                added_by="admin",
                added_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                is_active=True,
            )
        ])
        await FileTweetStore(root).save_tweets(
            [
                Tweet(
                    tweet_id="tw_001",
                    text="Hello",
                    author_username="alice",
                    created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
                )
            ],
            early_stop_threshold=0,
        )
        await FileSummaryStore(root).seed([
            SummaryRecord(
                summary_id="sum_001",
                tweet_id="tw_001",
                summary_text="摘要",
                model_provider="openrouter",
                model_name="gpt-4",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                cost_usd=0.01,
                content_hash="hash1",
                created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
                updated_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            )
        ])

    asyncio.run(_seed())


class TestImportConfig:
    def test_import_follows_insert(self, monkeypatch, tmp_path):
        _pin_file_root(monkeypatch, tmp_path)
        pkg = _make_package(
            {
                "config": {
                    "scraper_follows": [
                        _follow_item("alice", "KOL"),
                        _follow_item("bob", "Dev"),
                    ],
                }
            }
        )

        svc = ImportService()
        result = svc.import_data(pkg)

        assert result.success
        assert result.stats["scraper_follows"].inserted == 2

        follows = asyncio.run(FileFollowStore(tmp_path).get_all_follows(include_inactive=True))
        assert len(follows) == 2

    def test_import_follows_skip_existing(self, monkeypatch, tmp_path):
        _pin_file_root(monkeypatch, tmp_path)

        # 预插入 alice
        asyncio.run(FileFollowStore(tmp_path).seed([_follow_seed("alice", "Existing")]))

        pkg = _make_package(
            {
                "config": {
                    "scraper_follows": [
                        _follow_item("alice", "New"),
                    ],
                }
            }
        )

        svc = ImportService()
        result = svc.import_data(pkg, strategy=ConflictStrategy.skip)

        assert result.stats["scraper_follows"].skipped == 1

        # 验证未被覆盖
        alice = asyncio.run(FileFollowStore(tmp_path).get_follow_by_username("alice"))
        assert alice is not None
        assert alice.reason == "Existing"

    def test_import_follows_overwrite(self, monkeypatch, tmp_path):
        _pin_file_root(monkeypatch, tmp_path)

        asyncio.run(FileFollowStore(tmp_path).seed([_follow_seed("alice", "Old")]))

        pkg = _make_package(
            {
                "config": {
                    "scraper_follows": [
                        _follow_item("alice", "New", "import"),
                    ],
                }
            }
        )

        svc = ImportService()
        result = svc.import_data(pkg, strategy=ConflictStrategy.overwrite)

        assert result.stats["scraper_follows"].updated == 1

        alice = asyncio.run(FileFollowStore(tmp_path).get_follow_by_username("alice"))
        assert alice is not None
        assert alice.reason == "New"


class TestImportContent:
    def test_import_tweets_and_summaries(self, monkeypatch, tmp_path):
        _pin_file_root(monkeypatch, tmp_path)

        pkg = _make_package(
            {
                "content": {
                    "tweets": [
                        {
                            "tweet_id": "tw_001",
                            "text": "Hello",
                            "created_at": "2026-02-01T00:00:00+00:00",
                            "author_username": "alice",
                        },
                    ],
                    "summaries": [
                        {
                            "summary_id": "sum_001",
                            "tweet_id": "tw_001",
                            "summary_text": "摘要",
                            "model_provider": "openrouter",
                            "model_name": "gpt-4",
                            "prompt_tokens": 100,
                            "completion_tokens": 50,
                            "total_tokens": 150,
                            "cost_usd": 0.01,
                            "content_hash": "hash1",
                            "created_at": "2026-02-01T00:00:00+00:00",
                        },
                    ],
                    "articles": [
                        {
                            "tweet_id": "tw_001",
                            "title": "Article Title",
                            "content": "Full text",
                        },
                    ],
                }
            }
        )

        svc = ImportService()
        result = svc.import_data(pkg)

        assert result.success
        assert result.stats["tweets"].inserted == 1
        assert result.stats["summaries"].inserted == 1
        assert result.stats["articles"].inserted == 1

    def test_tweets_merge_skips_existing(self, monkeypatch, tmp_path):
        """merge 策略下 tweets 不可变，已存在则跳过。"""
        _pin_file_root(monkeypatch, tmp_path)

        asyncio.run(
            FileTweetStore(tmp_path).save_tweets(
                [
                    Tweet(
                        tweet_id="tw_001",
                        text="Original",
                        created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
                        author_username="alice",
                    )
                ],
                early_stop_threshold=0,
            )
        )

        pkg = _make_package(
            {
                "content": {
                    "tweets": [
                        {
                            "tweet_id": "tw_001",
                            "text": "Modified",
                            "created_at": "2026-02-01T00:00:00+00:00",
                            "author_username": "alice",
                        },
                    ],
                    "summaries": [],
                    "articles": [],
                }
            }
        )

        svc = ImportService()
        result = svc.import_data(pkg, strategy=ConflictStrategy.merge)

        assert result.stats["tweets"].skipped == 1

        tweets = asyncio.run(FileTweetStore(tmp_path).get_all_tweets())
        tweet = next(t for t in tweets if t.tweet_id == "tw_001")
        assert tweet.text == "Original"


class TestDryRun:
    def test_dry_run_does_not_persist(self, monkeypatch, tmp_path):
        _pin_file_root(monkeypatch, tmp_path)

        pkg = _make_package(
            {
                "config": {
                    "scraper_follows": [
                        _follow_item("alice", "KOL"),
                    ],
                }
            }
        )

        svc = ImportService()
        result = svc.import_data(pkg, dry_run=True)

        assert result.dry_run
        assert result.stats["scraper_follows"].inserted == 1  # 统计仍然计数

        # 但数据库中没有数据
        follows = asyncio.run(FileFollowStore(tmp_path).get_all_follows(include_inactive=True))
        assert len(follows) == 0


class TestCategoryFiltering:
    def test_import_only_config(self, monkeypatch, tmp_path):
        _pin_file_root(monkeypatch, tmp_path)

        pkg = _make_package(
            {
                "config": {
                    "scraper_follows": [
                        _follow_item("alice", "KOL"),
                    ],
                },
                "content": {
                    "tweets": [
                        {
                            "tweet_id": "tw_001",
                            "text": "Hello",
                            "created_at": "2026-02-01T00:00:00+00:00",
                            "author_username": "alice",
                        },
                    ],
                    "summaries": [],
                    "articles": [],
                },
            },
            categories=["config", "content"],
        )

        svc = ImportService()
        result = svc.import_data(pkg, categories=[SyncCategory.config])

        assert "scraper_follows" in result.stats
        assert "tweets" not in result.stats


class TestFullRoundtrip:
    """完整 export → import 往返测试。"""

    def test_export_then_import(self, monkeypatch, tmp_path):
        """导出数据库内容，清空后导入，验证数据一致性。"""
        from src.sync.services.export_service import ExportService

        # 导出源已固定文件层。
        src_root = tmp_path / "source"
        monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
        monkeypatch.setenv("XWATCHER_DATA_ROOT", str(src_root))
        _seed_file_roundtrip_data(src_root)
        pkg = ExportService().export(instance_id="source")

        # 创建目标文件根并导入
        dst_root = tmp_path / "target"
        monkeypatch.setenv("XWATCHER_DATA_ROOT", str(dst_root))

        result = ImportService().import_data(pkg)
        assert result.success

        # 验证数据一致性
        follows = asyncio.run(FileFollowStore(dst_root).get_all_follows(include_inactive=True))
        assert len(follows) == 1
        assert follows[0].username == "alice"

        tweets = asyncio.run(FileTweetStore(dst_root).get_all_tweets())
        assert len(tweets) == 1
        assert tweets[0].tweet_id == "tw_001"

        summaries = asyncio.run(FileSummaryStore(dst_root).get_all_summaries())
        assert len(summaries) == 1
