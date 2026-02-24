"""Import 服务测试。"""

from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from src.database.models import Base, ScraperFollow, ScraperScheduleConfig
from src.scraper.infrastructure.article_models import ArticleOrm
from src.scraper.infrastructure.models import TweetOrm
from src.summarization.infrastructure.models import SummaryOrm
from src.sync.domain.models import (
    ConflictStrategy,
    ExportFilters,
    ExportMetadata,
    ExportPackage,
    SyncCategory,
)
from src.sync.services.import_service import ImportService
from src.topic.infrastructure.models import TopicAccountOrm, TopicOrm


def _make_session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine), engine


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


class TestImportConfig:
    def test_import_follows_insert(self):
        factory, engine = _make_session_factory()
        pkg = _make_package({
            "config": {
                "scraper_follows": [
                    {"username": "alice", "reason": "KOL", "added_by": "admin", "is_active": True},
                    {"username": "bob", "reason": "Dev", "added_by": "admin", "is_active": True},
                ],
                "scraper_schedule_config": None,
            }
        })

        svc = ImportService(factory)
        result = svc.import_data(pkg)

        assert result.success
        assert result.stats["scraper_follows"].inserted == 2

        with Session(engine) as session:
            follows = session.execute(select(ScraperFollow)).scalars().all()
            assert len(follows) == 2

    def test_import_follows_skip_existing(self):
        factory, engine = _make_session_factory()

        # 预插入 alice
        with Session(engine) as session:
            session.add(ScraperFollow(username="alice", reason="Existing", added_by="admin"))
            session.commit()

        pkg = _make_package({
            "config": {
                "scraper_follows": [
                    {"username": "alice", "reason": "New", "added_by": "admin"},
                ],
                "scraper_schedule_config": None,
            }
        })

        svc = ImportService(factory)
        result = svc.import_data(pkg, strategy=ConflictStrategy.skip)

        assert result.stats["scraper_follows"].skipped == 1

        # 验证未被覆盖
        with Session(engine) as session:
            alice = session.execute(
                select(ScraperFollow).where(ScraperFollow.username == "alice")
            ).scalar_one()
            assert alice.reason == "Existing"

    def test_import_follows_overwrite(self):
        factory, engine = _make_session_factory()

        with Session(engine) as session:
            session.add(ScraperFollow(username="alice", reason="Old", added_by="admin"))
            session.commit()

        pkg = _make_package({
            "config": {
                "scraper_follows": [
                    {"username": "alice", "reason": "New", "added_by": "import"},
                ],
                "scraper_schedule_config": None,
            }
        })

        svc = ImportService(factory)
        result = svc.import_data(pkg, strategy=ConflictStrategy.overwrite)

        assert result.stats["scraper_follows"].updated == 1

        with Session(engine) as session:
            alice = session.execute(
                select(ScraperFollow).where(ScraperFollow.username == "alice")
            ).scalar_one()
            assert alice.reason == "New"

    def test_import_schedule_config(self):
        factory, engine = _make_session_factory()

        pkg = _make_package({
            "config": {
                "scraper_follows": [],
                "scraper_schedule_config": {
                    "interval_seconds": 86400,
                    "is_enabled": True,
                    "updated_by": "import",
                },
            }
        })

        svc = ImportService(factory)
        result = svc.import_data(pkg)

        assert result.stats["scraper_schedule_config"].inserted == 1

        with Session(engine) as session:
            config = session.execute(
                select(ScraperScheduleConfig).where(ScraperScheduleConfig.id == 1)
            ).scalar_one()
            assert config.interval_seconds == 86400


class TestImportContent:
    def test_import_tweets_and_summaries(self):
        factory, engine = _make_session_factory()

        pkg = _make_package({
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
        })

        svc = ImportService(factory)
        result = svc.import_data(pkg)

        assert result.success
        assert result.stats["tweets"].inserted == 1
        assert result.stats["summaries"].inserted == 1
        assert result.stats["articles"].inserted == 1

    def test_tweets_merge_skips_existing(self):
        """merge 策略下 tweets 不可变，已存在则跳过。"""
        factory, engine = _make_session_factory()

        with Session(engine) as session:
            session.add(TweetOrm(
                tweet_id="tw_001",
                text="Original",
                created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
                author_username="alice",
            ))
            session.commit()

        pkg = _make_package({
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
        })

        svc = ImportService(factory)
        result = svc.import_data(pkg, strategy=ConflictStrategy.merge)

        assert result.stats["tweets"].skipped == 1

        with Session(engine) as session:
            tweet = session.execute(
                select(TweetOrm).where(TweetOrm.tweet_id == "tw_001")
            ).scalar_one()
            assert tweet.text == "Original"


class TestImportTopics:
    def test_import_topic_with_accounts(self):
        factory, engine = _make_session_factory()

        pkg = _make_package({
            "topics": {
                "topics": [
                    {
                        "name": "AI Research",
                        "description": "AI 研究动态",
                        "accounts": ["alice", "bob"],
                        "summary_tasks": [],
                    },
                ],
            }
        })

        svc = ImportService(factory)
        result = svc.import_data(pkg)

        assert result.success
        assert result.stats["topics"].inserted == 1

        with Session(engine) as session:
            topic = session.execute(select(TopicOrm)).scalar_one()
            assert topic.name == "AI Research"
            accounts = session.execute(
                select(TopicAccountOrm).where(TopicAccountOrm.topic_id == topic.id)
            ).scalars().all()
            assert len(accounts) == 2

    def test_merge_topics_adds_new_accounts(self):
        factory, engine = _make_session_factory()

        # 预插入 topic
        with Session(engine) as session:
            topic = TopicOrm(name="AI Research", description="AI")
            session.add(topic)
            session.flush()
            session.add(TopicAccountOrm(topic_id=topic.id, username="alice"))
            session.commit()

        pkg = _make_package({
            "topics": {
                "topics": [
                    {
                        "name": "AI Research",
                        "accounts": ["alice", "bob", "charlie"],
                        "summary_tasks": [],
                    },
                ],
            }
        })

        svc = ImportService(factory)
        result = svc.import_data(pkg, strategy=ConflictStrategy.merge)

        assert result.stats["topics"].updated == 1

        with Session(engine) as session:
            topic = session.execute(
                select(TopicOrm).where(TopicOrm.name == "AI Research")
            ).scalar_one()
            accounts = session.execute(
                select(TopicAccountOrm).where(TopicAccountOrm.topic_id == topic.id)
            ).scalars().all()
            usernames = {a.username for a in accounts}
            assert usernames == {"alice", "bob", "charlie"}

    def test_import_topic_with_summary_task(self):
        factory, engine = _make_session_factory()

        pkg = _make_package({
            "topics": {
                "topics": [
                    {
                        "name": "AI",
                        "accounts": [],
                        "summary_tasks": [
                            {
                                "time_span_hours": 24,
                                "deadline": "2026-02-02T00:00:00+00:00",
                                "status": "completed",
                                "summary": {
                                    "content": "Summary text",
                                    "llm_provider": "openrouter",
                                    "llm_model": "gpt-4",
                                },
                            },
                        ],
                    },
                ],
            }
        })

        svc = ImportService(factory)
        result = svc.import_data(pkg)

        assert result.success
        assert result.stats["topics"].inserted == 1


class TestDryRun:
    def test_dry_run_does_not_persist(self):
        factory, engine = _make_session_factory()

        pkg = _make_package({
            "config": {
                "scraper_follows": [
                    {"username": "alice", "reason": "KOL", "added_by": "admin"},
                ],
                "scraper_schedule_config": None,
            }
        })

        svc = ImportService(factory)
        result = svc.import_data(pkg, dry_run=True)

        assert result.dry_run
        assert result.stats["scraper_follows"].inserted == 1  # 统计仍然计数

        # 但数据库中没有数据
        with Session(engine) as session:
            follows = session.execute(select(ScraperFollow)).scalars().all()
            assert len(follows) == 0


class TestCategoryFiltering:
    def test_import_only_config(self):
        factory, engine = _make_session_factory()

        pkg = _make_package(
            {
                "config": {
                    "scraper_follows": [
                        {"username": "alice", "reason": "KOL", "added_by": "admin"},
                    ],
                    "scraper_schedule_config": None,
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

        svc = ImportService(factory)
        result = svc.import_data(pkg, categories=[SyncCategory.config])

        assert "scraper_follows" in result.stats
        assert "tweets" not in result.stats


class TestFullRoundtrip:
    """完整 export → import 往返测试。"""

    def test_export_then_import(self):
        """导出数据库内容，清空后导入，验证数据一致性。"""
        from src.sync.services.export_service import ExportService

        # 创建源数据库并填充数据
        src_engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(src_engine)

        with Session(src_engine) as session:
            session.add(ScraperFollow(
                username="alice", reason="KOL", added_by="admin",
                added_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ))
            session.add(TweetOrm(
                tweet_id="tw_001", text="Hello", author_username="alice",
                created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            ))
            session.add(SummaryOrm(
                summary_id="sum_001", tweet_id="tw_001", summary_text="摘要",
                model_provider="openrouter", model_name="gpt-4",
                prompt_tokens=100, completion_tokens=50, total_tokens=150,
                cost_usd=0.01, content_hash="hash1",
            ))
            topic = TopicOrm(name="AI", description="AI Research")
            session.add(topic)
            session.flush()
            session.add(TopicAccountOrm(topic_id=topic.id, username="alice"))
            session.commit()

        # 导出
        with Session(src_engine) as session:
            pkg = ExportService(session).export(instance_id="source")

        # 创建目标数据库并导入
        dst_engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(dst_engine)
        dst_factory = sessionmaker(bind=dst_engine)

        result = ImportService(dst_factory).import_data(pkg)
        assert result.success

        # 验证数据一致性
        with Session(dst_engine) as session:
            follows = session.execute(select(ScraperFollow)).scalars().all()
            assert len(follows) == 1
            assert follows[0].username == "alice"

            tweets = session.execute(select(TweetOrm)).scalars().all()
            assert len(tweets) == 1
            assert tweets[0].tweet_id == "tw_001"

            summaries = session.execute(select(SummaryOrm)).scalars().all()
            assert len(summaries) == 1

            topics = session.execute(select(TopicOrm)).scalars().all()
            assert len(topics) == 1
            assert topics[0].name == "AI"
