"""Sync CLI 命令测试。"""

import asyncio
import json
from datetime import UTC, datetime

from click.testing import CliRunner

from src.cli.main import cli
from src.preference.domain.models import ScraperFollow as FollowDomain
from src.preference.infrastructure.file_follow_repository import FileFollowStore
from src.scraper.domain.models import Tweet
from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
from src.summarization.domain.models import SummaryRecord
from src.summarization.infrastructure.file_summary_repository import FileSummaryStore


def _seed_file_data(root, *, follows=None, tweets=None, summaries=None) -> None:
    async def _seed() -> None:
        if follows:
            await FileFollowStore(root).seed(follows)
        if tweets:
            await FileTweetStore(root).save_tweets(tweets, early_stop_threshold=0)
        if summaries:
            await FileSummaryStore(root).seed(summaries)

    asyncio.run(_seed())


class TestExportCommand:
    def test_export_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["export", "--help"])
        assert result.exit_code == 0
        assert "--categories" in result.output
        assert "--since" in result.output
        assert "--pretty" in result.output

    def test_export_creates_file(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
        monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
        _seed_file_data(
            tmp_path,
            follows=[
                FollowDomain(
                    id=1,
                    username="alice",
                    reason="KOL",
                    added_by="admin",
                    added_at=datetime(2026, 1, 1, tzinfo=UTC),
                    is_active=True,
                )
            ],
        )

        output_path = str(tmp_path / "test-export.json")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "export",
                "--output",
                output_path,
                "--categories",
                "config",
                "--instance-id",
                "test-server",
            ],
        )

        assert result.exit_code == 0, f"Failed: {result.output}"
        assert "导出完成" in result.output
        assert "scraper_follows: 1" in result.output

        # 验证文件内容
        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["metadata"]["source_instance_id"] == "test-server"
        assert len(data["data"]["config"]["scraper_follows"]) == 1

    def test_export_pretty(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
        monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
        output_path = str(tmp_path / "pretty.json")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "export",
                "--output",
                output_path,
                "--pretty",
            ],
        )

        assert result.exit_code == 0
        content = open(output_path, "r", encoding="utf-8").read()
        assert "\n  " in content

    def test_export_with_since_filter(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
        monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
        _seed_file_data(
            tmp_path,
            tweets=[
                Tweet(
                    tweet_id="tw_old",
                    text="Old tweet",
                    author_username="alice",
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                ),
                Tweet(
                    tweet_id="tw_new",
                    text="New tweet",
                    author_username="alice",
                    created_at=datetime(2026, 2, 15, tzinfo=UTC),
                ),
            ],
        )

        output_path = str(tmp_path / "filtered.json")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "export",
                "--output",
                output_path,
                "--categories",
                "content",
                "--since",
                "2026-02-01",
            ],
        )

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

    def test_import_data_from_file(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
        monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))

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
                },
            },
        }

        file_path = tmp_path / "import.json"
        file_path.write_text(json.dumps(export_data), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "import-data",
                str(file_path),
            ],
        )

        assert result.exit_code == 0, f"Failed: {result.output}"
        assert "导入完成" in result.output
        assert "插入 1" in result.output

        # 验证数据
        follows = asyncio.run(FileFollowStore(tmp_path).get_all_follows(include_inactive=True))
        assert len(follows) == 1
        assert follows[0].username == "alice"

    def test_import_dry_run(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
        monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))

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
                },
            },
        }

        file_path = tmp_path / "import.json"
        file_path.write_text(json.dumps(export_data), encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "import-data",
                str(file_path),
                "--dry-run",
            ],
        )

        assert result.exit_code == 0
        assert "预览模式" in result.output

        # dry-run 不应写入数据
        follows = asyncio.run(FileFollowStore(tmp_path).get_all_follows(include_inactive=True))
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

    def test_export_then_import(self, monkeypatch, tmp_path):
        # 导出源已固定文件层。
        source_root = tmp_path / "source-data"
        monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
        monkeypatch.setenv("XWATCHER_DATA_ROOT", str(source_root))
        _seed_file_data(
            source_root,
            follows=[
                FollowDomain(
                    id=1,
                    username="alice",
                    reason="KOL",
                    added_by="admin",
                    added_at=datetime(2026, 1, 1, tzinfo=UTC),
                    is_active=True,
                )
            ],
            tweets=[
                Tweet(
                    tweet_id="tw_001",
                    text="Hello",
                    author_username="alice",
                    created_at=datetime(2026, 2, 1, tzinfo=UTC),
                )
            ],
            summaries=[
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
                    created_at=datetime(2026, 2, 1, tzinfo=UTC),
                    updated_at=datetime(2026, 2, 1, tzinfo=UTC),
                )
            ],
        )

        # Export
        export_path = str(tmp_path / "export.json")
        runner = CliRunner()
        result = runner.invoke(cli, ["export", "--output", export_path, "--pretty"])
        assert result.exit_code == 0, f"Export failed: {result.output}"

        # Import to new file data root
        dest_root = tmp_path / "dest-data"
        monkeypatch.setenv("XWATCHER_DATA_LAYER", "file")
        monkeypatch.setenv("XWATCHER_DATA_ROOT", str(dest_root))
        result = runner.invoke(cli, ["import-data", export_path])
        assert result.exit_code == 0, f"Import failed: {result.output}"
        assert "导入完成" in result.output

        # 验证数据
        follows = asyncio.run(FileFollowStore(dest_root).get_all_follows(include_inactive=True))
        assert len(follows) == 1

        tweets = asyncio.run(FileTweetStore(dest_root).get_all_tweets())
        assert len(tweets) == 1

        summary = asyncio.run(FileSummaryStore(dest_root).get_summary_by_tweet("tw_001"))
        assert summary is not None
