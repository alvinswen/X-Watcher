"""CHG-058 views 运维命令的退出码、预览与治疗闭环。"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from click.testing import CliRunner

from src.cli.main import cli
from src.storage import paths, views
from src.storage.jsonl_store import write_shard

_YEAR = 2_026


def _tweet(tweet_id: str, day: int = 1) -> dict[str, object]:
    # 固定注入时间：CLI 用例不依赖当天日期。
    when = datetime(_YEAR, 8, day, 12, tzinfo=UTC)
    return {
        "tweet_id": tweet_id,
        "text": f"tweet-{tweet_id}",
        "created_at": when.isoformat(),
        "author_username": "alice",
    }


def _seed(root: Path, records: list[dict[str, object]]) -> None:
    when = datetime(_YEAR, 8, 1, 12, tzinfo=UTC)
    write_shard(paths.canonical_shard(root, "alice", when), records)


def test_views_check_returns_zero_for_consistent_view(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    _seed(tmp_path, [_tweet("t1")])
    views.rebuild_by_day(tmp_path)

    result = CliRunner().invoke(cli, ["views", "check"])

    assert result.exit_code == 0
    assert f"数据根目录: {tmp_path}" in result.output
    assert "计数: 推文正本 1 条 / 按天索引副本 1 条" in result.output
    assert "结论: 一致" in result.output


def test_views_check_limits_each_bucket_unless_full(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    _seed(tmp_path, [_tweet(f"t{index:02d}") for index in range(25)])

    preview = CliRunner().invoke(cli, ["views", "check"])
    full = CliRunner().invoke(cli, ["views", "check", "--full"])

    assert preview.exit_code == 1
    assert "结论: 不一致" in preview.output
    assert "正本有副本无: 25 条" in preview.output
    assert "    - t19" in preview.output
    assert "    - t20" not in preview.output
    assert "仅显示前 20 条" in preview.output
    assert full.exit_code == 1
    assert "    - t24" in full.output
    assert "仅显示前 20 条" not in full.output


def test_views_check_wraps_errors_as_click_failure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))

    def fail(_root: Path):
        raise OSError("broken shard")

    monkeypatch.setattr(views, "reconcile_by_day", fail)
    result = CliRunner().invoke(cli, ["views", "check"])

    assert result.exit_code == 1
    assert "自查执行失败: OSError: broken shard" in result.output


def test_views_rebuild_prints_paths_and_repairs_inconsistency(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    _seed(tmp_path, [_tweet("t1")])
    ghost = paths.by_day_shard(tmp_path, date(_YEAR, 7, 31))
    write_shard(ghost, [_tweet("ghost")])

    result = CliRunner().invoke(cli, ["views", "rebuild", "--yes"])

    assert result.exit_code == 0
    assert f"将重写目录: {paths.by_day_dir(tmp_path)}" in result.output
    assert f"将重写现场记录: {paths.by_day_state_doc(tmp_path)}" in result.output
    assert "当前按天分片数: 1" in result.output
    assert "完成: 产出 1 天 · 清理幽灵 1 天" in result.output
    assert views.reconcile_by_day(tmp_path)[0] is True


def test_views_rebuild_prompts_unless_yes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    _seed(tmp_path, [_tweet("t1")])

    aborted = CliRunner().invoke(cli, ["views", "rebuild"], input="n\n")
    confirmed = CliRunner().invoke(cli, ["views", "rebuild"], input="y\n")

    assert aborted.exit_code == 1
    assert "确认执行重建？" in aborted.output
    assert confirmed.exit_code == 0
    assert "完成: 产出 1 天" in confirmed.output
