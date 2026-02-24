"""Sync CLI 命令测试。"""

import json
from datetime import datetime, timezone
from unittest.mock import patch

from click.testing import CliRunner
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from src.cli.main import cli
from src.database.models import Base, ScraperFollow
from src.scraper.infrastructure.models import TweetOrm
from src.summarization.infrastructure.models import SummaryOrm


def _make_test_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine


class TestExportCommand:
    def test_export_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["export", "--help"])
        assert result.exit_code == 0
        assert "--categories" in result.output
        assert "--since" in result.output
        assert "--pretty" in result.output

    def test_export_creates_file(self, tmp_path):
        engine = _make_test_engine()

        with Session(engine) as session:
            session.add(ScraperFollow(
                username="alice", reason="KOL", added_by="admin",
                added_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ))
            session.commit()

        output_path = str(tmp_path / "test-export.json")

        with patch("src.database.models.get_engine", return_value=engine):
            runner = CliRunner()
            result = runner.invoke(cli, [
                "export",
                "--output", output_path,
                "--categories", "config",
                "--instance-id", "test-server",
            ])

        assert result.exit_code == 0, f"Failed: {result.output}"
        assert "导出完成" in result.output
        assert "scraper_follows: 1" in result.output

        # 验证文件内容
        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["metadata"]["source_instance_id"] == "test-server"
        assert len(data["data"]["config"]["scraper_follows"]) == 1

    def test_export_pretty(self, tmp_path):
        engine = _make_test_engine()
        output_path = str(tmp_path / "pretty.json")

        with patch("src.database.models.get_engine", return_value=engine):
            runner = CliRunner()
            result = runner.invoke(cli, [
                "export", "--output", output_path, "--pretty",
            ])

        assert result.exit_code == 0
        content = open(output_path, "r", encoding="utf-8").read()
        assert "\n  " in content

    def test_export_with_since_filter(self, tmp_path):
        engine = _make_test_engine()

        with Session(engine) as session:
            session.add(TweetOrm(
                tweet_id="tw_old", text="Old tweet", author_username="alice",
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ))
            session.add(TweetOrm(
                tweet_id="tw_new", text="New tweet", author_username="alice",
                created_at=datetime(2026, 2, 15, tzinfo=timezone.utc),
            ))
            session.commit()

        output_path = str(tmp_path / "filtered.json")

        with patch("src.database.models.get_engine", return_value=engine):
            runner = CliRunner()
            result = runner.invoke(cli, [
                "export", "--output", output_path,
                "--categories", "content",
                "--since", "2026-02-01",
            ])

        assert result.exit_code == 0
        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["metadata"]["counts"]["tweets"] == 1


class TestImportDataCommand:
    def test_import_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["import-data", "--help"])
        assert result.exit_code == 0
        assert "--strategy" in result.output
        assert "--dry-run" in result.output
        assert "--force" in result.output

    def test_import_data_from_file(self, tmp_path):
        engine = _make_test_engine()

        # 创建导出文件
        export_data = {
            "metadata": {
                "format_version": "1.0",
                "schema_version": 1,
                "exported_at": "2026-02-24T12:00:00+00:00",
                "source_instance_id": "source-server",
                "categories": ["config"],
                "filters": {},
                "counts": {"scraper_follows": 1},
            },
            "data": {
                "config": {
                    "scraper_follows": [
                        {
                            "username": "alice",
                            "added_at": "2026-01-01T00:00:00+00:00",
                            "reason": "KOL",
                            "added_by": "admin",
                            "is_active": True,
                        },
                    ],
                    "scraper_schedule_config": None,
                },
            },
        }

        file_path = tmp_path / "import.json"
        file_path.write_text(json.dumps(export_data), encoding="utf-8")

        with patch("src.database.models.get_engine", return_value=engine):
            runner = CliRunner()
            result = runner.invoke(cli, [
                "import-data", str(file_path),
            ])

        assert result.exit_code == 0, f"Failed: {result.output}"
        assert "导入完成" in result.output
        assert "插入 1" in result.output

        # 验证数据
        with Session(engine) as session:
            follows = session.execute(select(ScraperFollow)).scalars().all()
            assert len(follows) == 1
            assert follows[0].username == "alice"

    def test_import_dry_run(self, tmp_path):
        engine = _make_test_engine()

        export_data = {
            "metadata": {
                "format_version": "1.0",
                "schema_version": 1,
                "exported_at": "2026-02-24T12:00:00+00:00",
                "source_instance_id": "source",
                "categories": ["config"],
            },
            "data": {
                "config": {
                    "scraper_follows": [
                        {"username": "alice", "reason": "KOL", "added_by": "admin"},
                    ],
                    "scraper_schedule_config": None,
                },
            },
        }

        file_path = tmp_path / "import.json"
        file_path.write_text(json.dumps(export_data), encoding="utf-8")

        with patch("src.database.models.get_engine", return_value=engine):
            runner = CliRunner()
            result = runner.invoke(cli, [
                "import-data", str(file_path), "--dry-run",
            ])

        assert result.exit_code == 0
        assert "预览模式" in result.output

        # dry-run 不应写入数据
        with Session(engine) as session:
            follows = session.execute(select(ScraperFollow)).scalars().all()
            assert len(follows) == 0

    def test_import_invalid_schema_version(self, tmp_path):
        export_data = {
            "metadata": {
                "schema_version": 999,
                "exported_at": "2026-01-01T00:00:00+00:00",
                "source_instance_id": "x",
            },
            "data": {},
        }

        file_path = tmp_path / "future.json"
        file_path.write_text(json.dumps(export_data), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(cli, ["import-data", str(file_path)])
        assert result.exit_code == 1
        assert "schema 版本不兼容" in result.output


class TestEndToEnd:
    """完整 export → import-data 端到端测试。"""

    def test_export_then_import(self, tmp_path):
        # 源数据库
        src_engine = _make_test_engine()
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
            session.commit()

        # Export
        export_path = str(tmp_path / "export.json")
        with patch("src.database.models.get_engine", return_value=src_engine):
            runner = CliRunner()
            result = runner.invoke(cli, ["export", "--output", export_path, "--pretty"])
        assert result.exit_code == 0, f"Export failed: {result.output}"

        # Import to new database
        dst_engine = _make_test_engine()
        with patch("src.database.models.get_engine", return_value=dst_engine):
            result = runner.invoke(cli, ["import-data", export_path])
        assert result.exit_code == 0, f"Import failed: {result.output}"
        assert "导入完成" in result.output

        # 验证数据
        with Session(dst_engine) as session:
            follows = session.execute(select(ScraperFollow)).scalars().all()
            assert len(follows) == 1

            tweets = session.execute(select(TweetOrm)).scalars().all()
            assert len(tweets) == 1

            summaries = session.execute(select(SummaryOrm)).scalars().all()
            assert len(summaries) == 1
