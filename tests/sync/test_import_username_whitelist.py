"""导入用户名严格白名单回归（CHG-041）。"""

import asyncio
from datetime import UTC, datetime

import pytest
from click.testing import CliRunner

from src.cli.main import cli
from src.scraper.infrastructure.file_tweet_repository import FileTweetStore
from src.shared.username import (
    is_valid_username_format,
    validate_username_format,
)
from src.sync.domain.models import ExportMetadata, ExportPackage
from src.sync.format.json_format import write_export_file
from src.sync.services.import_service import ImportService


def _make_package(data: dict, categories: list[str]) -> ExportPackage:
    return ExportPackage(
        metadata=ExportMetadata(
            exported_at=datetime(2026, 7, 21, tzinfo=UTC),
            source_instance_id="chg-041-test",
            categories=categories,
        ),
        data=data,
    )


def _tweet(tweet_id: str, username: object) -> dict:
    return {
        "tweet_id": tweet_id,
        "text": tweet_id,
        "created_at": "2026-07-21T00:00:00+00:00",
        "author_username": username,
    }


def _follow(username: object, *, platform_user_id: str = "123") -> dict:
    return {
        "username": username,
        "platform_user_id": platform_user_id,
        "reason": "test",
        "added_by": "test",
        "added_at": "2026-07-21T00:00:00+00:00",
        "is_active": True,
    }


@pytest.mark.parametrize("username", ["a", "a" * 15, "a_b", "A1_", "café"])
def test_strict_username_accepts_valid_boundaries(username):
    validate_username_format(username)
    assert is_valid_username_format(username) is True


@pytest.mark.parametrize(
    "username",
    ["", "a" * 16, "user@example", "two words", "../x", "/abs", "___"],
)
def test_strict_username_rejects_invalid_boundaries(username):
    with pytest.raises(ValueError):
        validate_username_format(username)
    assert is_valid_username_format(username) is False


def test_preview_blocks_invalid_tweets_without_failing(monkeypatch, tmp_path):
    """dry-run 阶段即可见拦截，合法条目不连坐且原输入不被改写。"""
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path / "data"))
    malicious = _tweet("blocked", "../../evil")
    package = _make_package(
        {
            "content": {
                "tweets": [
                    malicious,
                    _tweet("legal", "alice"),
                    _tweet("missing", None),
                    _tweet("non-string", 123),
                ],
                "summaries": [],
                "articles": [],
            }
        },
        ["content"],
    )

    result = ImportService().import_data(package, dry_run=True)

    assert result.success is True
    assert result.dry_run is True
    assert result.stats["tweets"].inserted == 1
    assert result.stats["tweets"].skipped == 3
    assert len(result.errors) == 1
    assert "[tweets] 已拦截 3 条" in result.errors[0]
    assert "'../../evil'" in result.errors[0]
    assert "磁盘" not in result.errors[0]
    assert malicious["author_username"] == "../../evil"


def test_execute_blocks_traversal_and_persists_legal_tweet(monkeypatch, tmp_path):
    """真写时数据根外 0 新文件，合法 tweet 正常落盘读回。"""
    data_root = tmp_path / "data-root"
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(data_root))
    package = _make_package(
        {
            "content": {
                "tweets": [
                    _tweet("blocked", "../../evil"),
                    _tweet("legal", "alice"),
                ],
                "summaries": [],
                "articles": [],
            }
        },
        ["content"],
    )

    before_outside = {
        path.relative_to(tmp_path)
        for path in tmp_path.rglob("*")
        if path.is_file() and data_root not in path.parents
    }
    result = ImportService().import_data(package)
    after_outside = {
        path.relative_to(tmp_path)
        for path in tmp_path.rglob("*")
        if path.is_file() and data_root not in path.parents
    }

    assert result.success is True
    assert result.stats["tweets"].inserted == 1
    assert result.stats["tweets"].skipped == 1
    assert before_outside == after_outside
    assert not any("evil" in path.parts for path in data_root.rglob("*"))
    tweets = asyncio.run(FileTweetStore(data_root).get_all_tweets())
    assert [tweet.tweet_id for tweet in tweets] == ["legal"]


def test_follows_validate_username_only(monkeypatch, tmp_path):
    """follows 拦截 username，但 platform_user_id 不参与格式校验。"""
    data_root = tmp_path / "data-root"
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(data_root))
    package = _make_package(
        {
            "config": {
                "scraper_follows": [
                    _follow("../x"),
                    _follow("alice", platform_user_id="../../allowed-id"),
                ]
            }
        },
        ["config"],
    )

    result = ImportService().import_data(package)

    assert result.success is True
    assert result.stats["scraper_follows"].inserted == 1
    assert result.stats["scraper_follows"].skipped == 1
    assert "[scraper_follows] 已拦截 1 条" in result.errors[0]


def test_cli_import_reports_blocked_count_and_exits_zero(monkeypatch, tmp_path):
    """CLI 与 REST 共用服务层：拦截可见但仍成功退出。"""
    data_root = tmp_path / "data-root"
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(data_root))
    package = _make_package(
        {
            "content": {
                "tweets": [
                    _tweet("blocked", "../../evil"),
                    _tweet("legal", "alice"),
                ],
                "summaries": [],
                "articles": [],
            }
        },
        ["content"],
    )
    package_path = tmp_path / "package.json"
    write_export_file(package, package_path)

    result = CliRunner().invoke(cli, ["import-data", str(package_path)])

    assert result.exit_code == 0
    assert "tweets: 插入 1, 跳过 1" in result.output
    assert "[tweets] 已拦截 1 条" in result.output
    assert "导入完成!" in result.output


def test_blocked_examples_are_capped_at_five(monkeypatch, tmp_path):
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path / "data"))
    package = _make_package(
        {
            "content": {
                "tweets": [_tweet(f"blocked-{index}", f"../evil-{index}") for index in range(6)],
                "summaries": [],
                "articles": [],
            }
        },
        ["content"],
    )

    result = ImportService().import_data(package, dry_run=True)

    assert result.stats["tweets"].skipped == 6
    assert "'../evil-4'" in result.errors[0]
    assert "'../evil-5'" not in result.errors[0]
