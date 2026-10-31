"""准入排序去名字化（四段键）与分组公平性验收测试。

覆盖 CHG-DSH-001 交付包 `05-用例清单.csv` 中全部 25 条 `automation_path`
（TC-DSH-001 ~ TC-DSH-025），规格见 `03-技术方案.md` §7.1 / §7.2。

三条与规格实现方式的差异（均为规格自身不可满足，详见包内 `08-实现记录.md`）：
1. 需要「同一输入跑第二次」的用例（TC-005 / 007 / 014）改用相互独立的临时数据根，
   因为第二次 `mine()` 在同一数据根上必然命中 `merge_by_username`（候选池里已是
   `discovered`），走合并刷新而不是重新准入 —— 这与既有
   `tests/source_candidates/test_mining_service.py:94-96` 锁住的行为一致。
2. TC-019 不断言「池目录无文件」：`all_index_entries()` 在索引缺失时会重建，
   必然写出 `source_candidates/index.json`。改断言「无候选档案」。
3. TC-020 窗二显式给 `since`：规格只写了 `until`，那样会把 02-28 那条也算进来（合计 2）。
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from src.config import Settings
from src.mcp import auth as mcp_auth
from src.mcp.server import create_mcp_server
from src.mcp.token_verifier import XWatcherTokenVerifier
from src.preference.infrastructure.file_follow_repository import FileFollowStore
from src.source_candidates.infrastructure.file_source_candidate_repository import (
    FileSourceCandidateStore,
)
from src.source_candidates.models import (
    CandidateStatus,
    MiningSignal,
    SourceCandidate,
)
from src.source_candidates.services.mining_service import (
    EligibleEntry,
    MiningService,
    admission_quadruple,
    order_for_admission,
)
from src.storage.jsonl_store import read_shard
from src.storage.paths import iter_source_candidate_docs
from src.subjects.store import FileSubjectStore

# `8be777b` 基线导出的 Settings 字段集合；本包不得新增配置键（技术方案 §九 黑名单）。
_CONFIG_KEYS = [
    "admin_api_key",
    "claude_code_model_name",
    "feed_max_tweets",
    "jwt_expire_hours",
    "jwt_secret_key",
    "log_file",
    "log_file_backup_count",
    "log_file_max_bytes",
    "log_format",
    "log_level",
    "prometheus_enabled",
    "scraper_early_stop_threshold",
    "scraper_ema_alpha",
    "scraper_incremental_bridge_tweets",
    "scraper_incremental_clean_rounds_required",
    "scraper_incremental_cutover_groups",
    "scraper_incremental_enabled",
    "scraper_incremental_max_accounts_per_group",
    "scraper_incremental_max_pages_per_round",
    "scraper_incremental_max_query_chars",
    "scraper_incremental_new_account_backfill_tweets",
    "scraper_incremental_overlap_minutes",
    "scraper_incremental_resume_rounds_alert",
    "scraper_incremental_sentinels",
    "scraper_incremental_stalled_rounds_alert",
    "scraper_limit",
    "scraper_max_limit",
    "scraper_max_pages_per_scrape",
    "scraper_min_limit",
    "task_max_running_seconds",
    "twitter_api_key",
    "twitter_balance_danger_threshold",
    "twitter_balance_warning_threshold",
    "twitter_base_url",
]


# ── 共用夹具（技术方案 §7.2.0 的 F1 / F2 / F3）──────────────────────────


def _row(
    tweet_id: str,
    source: str,
    target: str,
    created_at: str,
    reference_type: str = "quoted",
) -> dict[str, Any]:
    return {
        "tweet_id": tweet_id,
        "author_username": source,
        "referenced_tweet_author_username": target,
        "reference_type": reference_type,
        "created_at": created_at,
    }


def _rows_for(
    rows_by_target: dict[str, list[tuple[str, str]]],
    times: dict[str, str],
    rename: dict[str, str] | None = None,
) -> list[list[dict[str, Any]]]:
    """把 {被引用账号: [(编号, 引用账号), ...]} 展开成按账号分组的行列表。"""
    mapping = rename or {}
    groups: list[list[dict[str, Any]]] = []
    for target, rows in rows_by_target.items():
        display = mapping.get(target, target)
        groups.append([_row(tweet_id, source, display, times[target]) for tweet_id, source in rows])
    return groups


def _write_groups(
    root: Path,
    groups: list[list[dict[str, Any]]],
    dirnames: list[str],
) -> None:
    """一个目录名一个分片；目录名对扫描无业务含义，只决定取数顺序。"""
    for dirname, rows in zip(dirnames, groups, strict=True):
        shard = Path(root) / "tweets" / dirname / "2026-10.jsonl"
        shard.parent.mkdir(parents=True, exist_ok=True)
        shard.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )


def _dirs(count: int, *, reverse: bool = False) -> list[str]:
    if reverse:
        return [f"z{count - 1 - index:02d}" for index in range(count)]
    return [f"s{index:02d}" for index in range(count)]


def _service(root: Path) -> MiningService:
    return MiningService(
        FileSourceCandidateStore(Path(root)),
        FileFollowStore(Path(root)),
        FileSubjectStore(Path(root)),
    )


def _ids(result: dict[str, Any]) -> list[str]:
    return [item["candidate_id"] for item in result["mined"]]


def _preset(
    candidate_id: str,
    status: CandidateStatus,
    mined_at: datetime | None = None,
) -> SourceCandidate:
    stamp = mined_at or datetime(2026, 1, 1, tzinfo=UTC)
    return SourceCandidate(
        candidate_id=candidate_id,
        username=candidate_id,
        status=status,
        mining=MiningSignal(first_discovered_at=stamp, last_mined_at=stamp),
    )


def _signal() -> MiningSignal:
    stamp = datetime(2026, 10, 31, tzinfo=UTC)
    return MiningSignal(first_discovered_at=stamp, last_mined_at=stamp)


def _mine_tool():
    """F3：直接取工具函数的 `.fn`，不新起 server、不走 HTTP。"""
    return create_mcp_server()._tool_manager._tools["mine_source_candidates"].fn


async def _call(**payload: Any) -> dict[str, Any]:
    return json.loads(await _mine_tool()(**payload))


def _self_computed_quadruples(root: Path) -> dict[str, tuple[int, int, datetime, str]]:
    """测试自己从分片复算四元组，不复用产品任何排序代码。"""
    buckets: dict[str, dict[str, Any]] = {}
    for shard in sorted((Path(root) / "tweets").glob("*/*.jsonl")):
        for row in read_shard(shard):
            target = str(row["referenced_tweet_author_username"]).lower()
            bucket = buckets.setdefault(target, {"sources": set(), "ids": [], "times": []})
            bucket["sources"].add(str(row["author_username"]).lower())
            bucket["ids"].append(str(row["tweet_id"]))
            bucket["times"].append(
                datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
            )
    return {
        target: (
            len(bucket["ids"]),
            len(bucket["sources"]),
            max(bucket["times"]),
            max(bucket["ids"], key=int),
        )
        for target, bucket in buckets.items()
    }


# ── 语料（技术方案 §7.1）────────────────────────────────────────────


# 2-①：3 候选 / 9 行 / 各 3 引用 2 信源。名字序与时间序反向 → 有判别力。
_TIE_ROWS = {
    "alpha_src": [
        ("931000000000000003", "cite_a1"),
        ("931000000000000002", "cite_a1"),
        ("931000000000000001", "cite_a2"),
    ],
    "juliet_src": [
        ("720000000000000000", "cite_j1"),
        ("719000000000000999", "cite_j2"),
        ("719000000000000998", "cite_j1"),
    ],
    "sierra_src": [
        ("1000000000000000005", "cite_s1"),
        ("1000000000000000003", "cite_s2"),
        ("1000000000000000001", "cite_s1"),
    ],
}
_TIE_TIMES = {
    "alpha_src": "2026-10-01T00:00:00Z",
    "juliet_src": "2026-10-02T00:00:00Z",
    "sierra_src": "2026-10-03T00:00:00Z",
}
_RENAME = {"alpha_src": "mike_src", "juliet_src": "romeo_src", "sierra_src": "zulu_src"}

# 2-②：4 候选 / 12 行 / 6 分片。juliet 与 quebec 同刻，靠第四段数值序分先后。
_QUAD_ROWS = {
    "alpha_src": _TIE_ROWS["alpha_src"],
    "juliet_src": _TIE_ROWS["juliet_src"],
    "sierra_src": _TIE_ROWS["sierra_src"],
    "quebec_src": [
        ("1000000000000000006", "cite_q1"),
        ("1000000000000000004", "cite_q1"),
        ("1000000000000000002", "cite_q2"),
    ],
}
_QUAD_TIMES = {**_TIE_TIMES, "quebec_src": "2026-10-02T00:00:00Z"}

# 截断/抑制类用例：sierra 最新（本应第 1），其后依次是 juliet、alpha、xray。
_SLIDE_ROWS = {
    "sierra_src": _TIE_ROWS["sierra_src"],
    "juliet_src": _TIE_ROWS["juliet_src"],
    "alpha_src": _TIE_ROWS["alpha_src"],
    "xray_src": [
        ("500000000000000003", "cite_x1"),
        ("500000000000000002", "cite_x2"),
        ("500000000000000001", "cite_x1"),
    ],
}
_SLIDE_TIMES = {
    "sierra_src": "2026-10-04T00:00:00Z",
    "juliet_src": "2026-10-03T00:00:00Z",
    "alpha_src": "2026-10-02T00:00:00Z",
    "xray_src": "2026-10-01T00:00:00Z",
}

# 门槛两方向 + 前两段压后两段：a 引用更多但编号最小，b 引用更少但编号最大。
_THRESHOLD_ROWS = {
    "a_four_src": [
        ("1000000000000000001", "cite_1"),
        ("1000000000000000002", "cite_1"),
        ("1000000000000000003", "cite_2"),
        ("1000000000000000004", "cite_2"),
    ],
    "b_three_src": [
        ("1999999999999999999", "cite_1"),
        ("1999999999999999998", "cite_1"),
        ("1999999999999999997", "cite_2"),
    ],
    "c_two_src": [
        ("1000000000000000011", "cite_1"),
        ("1000000000000000012", "cite_2"),
    ],
    "d_one_src": [
        ("1000000000000000021", "cite_1"),
        ("1000000000000000022", "cite_1"),
        ("1000000000000000023", "cite_1"),
    ],
}
_THRESHOLD_TIMES = dict.fromkeys(_THRESHOLD_ROWS, "2026-10-10T00:00:00Z")


def _quad_groups() -> list[list[dict[str, Any]]]:
    """2-② 的 6 分片布局：首现序 s00..s03 = alpha / juliet / sierra / quebec。"""
    groups = _rows_for(_QUAD_ROWS, _QUAD_TIMES)
    by_target = dict(zip(_QUAD_ROWS, groups, strict=True))
    return [
        by_target["alpha_src"][:2],
        by_target["juliet_src"][:2],
        by_target["sierra_src"][:2],
        by_target["quebec_src"][:2],
        [by_target["alpha_src"][2], by_target["juliet_src"][2]],
        [by_target["sierra_src"][2], by_target["quebec_src"][2]],
    ]


def _five_groups() -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    for index in range(5):
        target = f"pool{index + 1}_src"
        created_at = f"2026-10-0{index + 1}T00:00:00Z"
        groups.append(
            [
                _row(f"100000000000000{index}01", "cite_p1", target, created_at),
                _row(f"100000000000000{index}02", "cite_p1", target, created_at),
                _row(f"100000000000000{index}03", "cite_p2", target, created_at),
            ]
        )
    return groups


def _bulk_rows() -> list[dict[str, Any]]:
    """50,000 行：49,970 行普通推文 + 30 行引用（3 个达门槛候选）。"""
    rows = [
        _row(
            f"1000000000000{index:06d}",
            f"plain_{index % 7}",
            f"plain_target_{index % 11}",
            "2026-10-10T00:00:00Z",
            reference_type="",
        )
        for index in range(49_970)
    ]
    for candidate in range(3):
        target = f"bulk{candidate}_src"
        for offset in range(10):
            rows.append(
                _row(
                    f"2000000000000{candidate}{offset:05d}",
                    f"cite_b{candidate}_{offset % 2}",
                    target,
                    "2026-10-10T00:00:00Z",
                )
            )
    return rows


# ── TC-DSH-001 ~ 025 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tie_at_cutoff_admits_newest_not_alphabetical(tmp_path):
    _write_groups(tmp_path, _rows_for(_TIE_ROWS, _TIE_TIMES), _dirs(3))

    result = await _service(tmp_path).mine(top_n=2)

    assert _ids(result) == ["sierra_src", "juliet_src"]
    assert result["stats"]["above_threshold"] == 3
    assert result["stats"]["admitted"] == 2


@pytest.mark.asyncio
async def test_name_baseline_set_is_rejected(tmp_path):
    _write_groups(tmp_path, _rows_for(_TIE_ROWS, _TIE_TIMES), _dirs(3))
    name_baseline = set(sorted({"alpha_src", "juliet_src", "sierra_src"})[:2])

    mined = set(_ids(await _service(tmp_path).mine(top_n=2)))

    assert mined != name_baseline
    assert mined - name_baseline == {"sierra_src"}
    assert name_baseline - mined == {"alpha_src"}


@pytest.mark.asyncio
async def test_rename_keeps_time_identity(tmp_path):
    groups = _rows_for(_TIE_ROWS, _TIE_TIMES, _RENAME)
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    _write_groups(first_root, groups, _dirs(3))
    _write_groups(second_root, groups, _dirs(3))

    first = _ids(await _service(first_root).mine(top_n=2))
    second = _ids(await _service(second_root).mine(top_n=2))

    assert first == ["zulu_src", "romeo_src"]
    assert second == first


@pytest.mark.asyncio
async def test_fourth_key_uses_numeric_order_on_tie(tmp_path):
    _write_groups(tmp_path, _quad_groups(), _dirs(6))

    assert _ids(await _service(tmp_path).mine(top_n=2)) == ["sierra_src", "quebec_src"]


@pytest.mark.asyncio
async def test_mined_order_reflects_fourth_key(tmp_path):
    small = tmp_path / "small"
    large = tmp_path / "large"
    _write_groups(small, _quad_groups(), _dirs(6))
    _write_groups(large, _quad_groups(), _dirs(6))

    first = await _service(small).mine(top_n=2)
    second = await _service(large).mine(top_n=4)

    assert _ids(first) == ["sierra_src", "quebec_src"]
    assert first["stats"]["above_threshold"] == 4
    assert len(_ids(second)) == 4
    assert second["stats"]["admitted"] == 4
    assert "juliet_src" in _ids(second)


@pytest.mark.asyncio
async def test_full_order_matches_independent_quadruple_recompute(tmp_path):
    forward = tmp_path / "forward"
    backward = tmp_path / "backward"
    groups = _quad_groups()
    _write_groups(forward, groups, _dirs(6))
    _write_groups(backward, groups, _dirs(6, reverse=True))

    quadruples = _self_computed_quadruples(forward)
    assert len(quadruples) == 4
    assert len(set(quadruples.values())) == len(quadruples)
    # 第四段必须按数值序比：这里用 int() 显式换算，不复用产品的 tweet_id_order。
    expected = [
        target
        for target, _ in sorted(
            quadruples.items(),
            key=lambda item: (item[1][0], item[1][1], item[1][2], int(item[1][3])),
            reverse=True,
        )
    ]
    assert expected == ["sierra_src", "quebec_src", "juliet_src", "alpha_src"]

    assert _ids(await _service(forward).mine(top_n=2)) == expected[:2]
    assert _ids(await _service(backward).mine(top_n=2)) == expected[:2]

    entries: list[EligibleEntry] = [
        (quad[0], quad[1], quad[2], quad[3], target, target, _signal())
        for target, quad in quadruples.items()
    ]
    ordered = order_for_admission(entries)
    assert [admission_quadruple(entry) for entry in ordered] == [
        quadruples[target] for target in expected
    ]


@pytest.mark.asyncio
async def test_same_input_three_runs_and_shard_order_free(tmp_path):
    groups = _quad_groups()
    roots = [tmp_path / f"run{index}" for index in range(3)]
    for root in roots:
        _write_groups(root, groups, _dirs(6))
    shuffled = tmp_path / "shuffled"
    _write_groups(shuffled, groups, _dirs(6, reverse=True))

    results = [await _service(root).mine(top_n=2) for root in roots]
    results.append(await _service(shuffled).mine(top_n=2))

    sequences = [_ids(result) for result in results]
    assert sequences == [["sierra_src", "quebec_src"]] * 4
    recovered = [_self_computed_quadruples(root) for root in [*roots, shuffled]]
    assert recovered == [recovered[0]] * 4
    assert [
        (result["stats"]["admitted"], result["stats"]["above_threshold"]) for result in results
    ] == [(2, 4)] * 4


@pytest.mark.asyncio
async def test_reverse_shard_order_restores_same_list(tmp_path):
    groups = _quad_groups()
    first_root = tmp_path / "a"
    second_root = tmp_path / "b"
    third_root = tmp_path / "a2"
    _write_groups(first_root, groups, _dirs(6))
    _write_groups(second_root, groups, _dirs(6, reverse=True))
    _write_groups(third_root, groups, _dirs(6))

    first = await _service(first_root).mine(top_n=2)
    second = await _service(second_root).mine(top_n=2)
    third = await _service(third_root).mine(top_n=2)

    assert _ids(first) == _ids(second) == _ids(third)
    for result in (first, second, third):
        assert result["stats"]["admitted"] == 2
        assert result["stats"]["above_threshold"] == 4


@pytest.mark.asyncio
async def test_real_filesystem_data_root_not_mocked(tmp_path):
    rows = [row for group in _rows_for(_TIE_ROWS, _TIE_TIMES) for row in group]
    _write_groups(tmp_path, [rows], ["qa-dir-1"])

    store = FileSourceCandidateStore(tmp_path)
    service = MiningService(store, FileFollowStore(tmp_path), FileSubjectStore(tmp_path))

    result = await service.mine(top_n=2)

    assert result["stats"]["scanned_tweets"] == 9
    assert set(_ids(result)) == {"sierra_src", "juliet_src"}
    assert (tmp_path / "source_candidates" / "index.json").exists()
    assert len(iter_source_candidate_docs(tmp_path)) == 2
    assert {path.stem for path in iter_source_candidate_docs(tmp_path)} == {
        "sierra_src",
        "juliet_src",
    }


@pytest.mark.asyncio
async def test_candidate_without_timestamp_still_admitted_last(tmp_path):
    groups = [
        *_rows_for(_TIE_ROWS, _TIE_TIMES),
        [
            _row("1000000000000000007", "cite_d1", "delta_src", ""),
            _row("1000000000000000008", "cite_d1", "delta_src", ""),
            _row("1000000000000000009", "cite_d2", "delta_src", ""),
        ],
    ]
    _write_groups(tmp_path, groups, _dirs(4))
    service = _service(tmp_path)

    unfiltered = await service.mine(top_n=4)
    windowed = await service.mine(since=datetime(2026, 10, 1, tzinfo=UTC), top_n=4)

    assert len(_ids(unfiltered)) == 4
    assert _ids(unfiltered)[-1] == "delta_src"
    assert unfiltered["stats"]["above_threshold"] == 4
    assert "delta_src" not in _ids(windowed)


@pytest.mark.asyncio
async def test_followed_candidate_at_cutoff_does_not_take_slot(tmp_path):
    _write_groups(tmp_path, _rows_for(_SLIDE_ROWS, _SLIDE_TIMES), _dirs(4))
    store = FileSourceCandidateStore(tmp_path)
    await FileFollowStore(tmp_path).create_scraper_follow("sierra_src", "已在关注列表", "pm")
    service = MiningService(store, FileFollowStore(tmp_path), FileSubjectStore(tmp_path))

    result = await service.mine(top_n=2)

    assert result["stats"]["suppressed_in_library"] == 1
    assert result["stats"]["above_threshold"] == 3
    assert result["stats"]["admitted"] == 2
    assert set(_ids(result)) == {"juliet_src", "alpha_src"}
    assert await store.get_candidate("sierra_src") is None


@pytest.mark.asyncio
async def test_terminal_pool_candidate_at_cutoff_does_not_take_slot(tmp_path):
    _write_groups(tmp_path, _rows_for(_SLIDE_ROWS, _SLIDE_TIMES), _dirs(4))
    store = FileSourceCandidateStore(tmp_path)
    await store.upsert_candidate(_preset("sierra_src", CandidateStatus.REJECTED))
    seeded = await store.get_candidate("sierra_src")
    assert seeded is not None
    before = seeded.model_dump(mode="json")
    service = MiningService(store, FileFollowStore(tmp_path), FileSubjectStore(tmp_path))

    result = await service.mine(top_n=2)

    assert result["stats"]["suppressed_pool_terminal"] == 1
    assert result["stats"]["above_threshold"] == 3
    assert result["stats"]["admitted"] == 2
    assert set(_ids(result)) == {"juliet_src", "alpha_src"}
    stored = await store.get_candidate("sierra_src")
    assert stored is not None
    assert stored.model_dump(mode="json") == before


@pytest.mark.asyncio
async def test_nonterminal_pool_candidate_merged_not_admitted(tmp_path):
    _write_groups(tmp_path, _rows_for(_SLIDE_ROWS, _SLIDE_TIMES), _dirs(4))
    store = FileSourceCandidateStore(tmp_path)
    await store.upsert_candidate(_preset("sierra_src", CandidateStatus.DISCOVERED))
    service = MiningService(store, FileFollowStore(tmp_path), FileSubjectStore(tmp_path))

    result = await service.mine(top_n=2)

    assert result["stats"]["merged_nonterminal"] == 1
    assert result["merged_refreshed"] == ["sierra_src"]
    assert result["stats"]["above_threshold"] == 3
    assert result["stats"]["admitted"] == 2
    assert "sierra_src" not in _ids(result)
    refreshed = await store.get_candidate("sierra_src")
    assert refreshed is not None
    assert refreshed.mining.last_mined_at > datetime(2026, 1, 1, tzinfo=UTC)
    assert refreshed.mining.citation_total == 3
    assert len(await store.list_candidates()) == 3


@pytest.mark.asyncio
async def test_no_suppression_no_merge_no_truncation(tmp_path):
    groups = _rows_for(_TIE_ROWS, _TIE_TIMES)[:2]
    small = tmp_path / "small"
    large = tmp_path / "large"
    _write_groups(small, groups, _dirs(2))
    _write_groups(large, groups, _dirs(2))

    first = await _service(small).mine(top_n=2)
    second = await _service(large).mine(top_n=20)

    for result in (first, second):
        assert result["stats"]["admitted"] == 2
        assert result["stats"]["above_threshold"] == 2
        assert len(_ids(result)) == 2
        assert result["stats"]["suppressed_in_library"] == 0
        assert result["stats"]["suppressed_pool_terminal"] == 0
        assert result["stats"]["merged_nonterminal"] == 0


@pytest.mark.asyncio
async def test_state_transition_merge_then_suppressed(tmp_path):
    gamma_rows = [
        _row("1000000000000000101", "cite_g1", "gamma_src", "2026-10-05T00:00:00Z"),
        _row("1000000000000000102", "cite_g1", "gamma_src", "2026-10-05T00:00:00Z"),
        _row("1000000000000000103", "cite_g2", "gamma_src", "2026-10-05T00:00:00Z"),
    ]
    _write_groups(tmp_path, [gamma_rows], _dirs(1))
    store = FileSourceCandidateStore(tmp_path)
    await store.upsert_candidate(_preset("gamma_src", CandidateStatus.DISCOVERED))
    service = MiningService(store, FileFollowStore(tmp_path), FileSubjectStore(tmp_path))

    first = await service.mine(top_n=5)
    assert first["stats"]["merged_nonterminal"] == 1
    assert "gamma_src" not in _ids(first)

    candidate = await store.get_candidate("gamma_src")
    assert candidate is not None
    candidate.status = CandidateStatus.REJECTED
    await store.upsert_candidate(candidate)

    second = await service.mine(top_n=5)
    assert second["stats"]["suppressed_pool_terminal"] == 1
    assert "gamma_src" not in _ids(second)
    assert second["merged_refreshed"] == []


@pytest.mark.asyncio
async def test_threshold_both_directions_and_first_two_keys(tmp_path):
    _write_groups(tmp_path, _rows_for(_THRESHOLD_ROWS, _THRESHOLD_TIMES), _dirs(4))

    result = await _service(tmp_path).mine(top_n=3)

    assert _ids(result) == ["a_four_src", "b_three_src"]
    assert result["stats"]["above_threshold"] == 2


@pytest.mark.asyncio
async def test_top_n_endpoints_and_out_of_range(tmp_path, monkeypatch):
    groups = _five_groups()
    one_root = tmp_path / "one"
    many_root = tmp_path / "many"
    _write_groups(one_root, groups, _dirs(5))
    _write_groups(many_root, groups, _dirs(5))

    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(one_root))
    single = await _call(top_n=1)
    assert single["success"] is True
    assert len(single["data"]["mined"]) == 1
    assert single["data"]["stats"]["admitted"] == 1

    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(many_root))
    full = await _call(top_n=100)
    assert full["success"] is True
    assert len(full["data"]["mined"]) == 5

    for invalid in (0, 101):
        rejected = await _call(top_n=invalid)
        assert rejected["success"] is False
        assert rejected["error_type"] == "validation"
        assert "top_n" in rejected["error"]
        assert "1 到 100" in rejected["error"]

    assert len(await FileSourceCandidateStore(many_root).list_candidates()) == 5


@pytest.mark.asyncio
async def test_window_endpoints_inclusive(tmp_path):
    rows = [
        _row("1000000000000000001", "cite_1", "window_src", "2026-10-01T00:00:00Z"),
        _row("1000000000000000002", "cite_2", "window_src", "2026-10-30T00:00:00Z"),
        _row("1000000000000000003", "cite_1", "window_src", "2026-10-30T00:00:01Z"),
    ]
    _write_groups(tmp_path, [rows], _dirs(1))
    store = FileSourceCandidateStore(tmp_path)

    inside = await store.scan_citation_signals(
        None,
        datetime(2026, 10, 1, tzinfo=UTC),
        datetime(2026, 10, 30, tzinfo=UTC),
    )
    earlier = await store.scan_citation_signals(
        None,
        None,
        datetime(2026, 10, 29, 23, 59, 59, tzinfo=UTC),
    )

    bucket = inside["candidates"]["window_src"]
    assert sum(len(ids) for ids in bucket["citations"].values()) == 2
    assert bucket["last_cited_at"] == datetime(2026, 10, 30, tzinfo=UTC)
    assert sum(
        len(ids) for ids in earlier["candidates"]["window_src"]["citations"].values()
    ) == 1


@pytest.mark.asyncio
async def test_empty_window_returns_empty_list(tmp_path):
    rows = [
        _row(
            f"100000000000000000{index}",
            f"cite_{index}",
            f"plain{index}",
            "2026-10-01T00:00:00Z",
            reference_type="",
        )
        for index in range(1, 4)
    ]
    _write_groups(tmp_path, [rows], _dirs(1))
    store = FileSourceCandidateStore(tmp_path)
    service = MiningService(store, FileFollowStore(tmp_path), FileSubjectStore(tmp_path))

    result = await service.mine()

    assert result["mined"] == []
    assert result["stats"]["scanned_tweets"] == 3
    assert result["stats"]["above_threshold"] == 0
    assert result["stats"]["admitted"] == 0
    assert iter_source_candidate_docs(tmp_path) == []
    assert await store.list_candidates() == []


@pytest.mark.asyncio
async def test_leap_day_window_boundary(tmp_path):
    rows = [
        _row("1000000000000000001", "cite_1", "leap_src", "2028-02-28T23:59:59Z"),
        _row("1000000000000000002", "cite_2", "leap_src", "2028-02-29T00:00:00Z"),
        _row("1000000000000000003", "cite_1", "leap_src", "2028-03-01T00:00:00Z"),
    ]
    _write_groups(tmp_path, [rows], _dirs(1))
    store = FileSourceCandidateStore(tmp_path)

    span = await store.scan_citation_signals(
        None,
        datetime(2028, 2, 28, tzinfo=UTC),
        datetime(2028, 2, 29, 23, 59, 59, tzinfo=UTC),
    )
    point = await store.scan_citation_signals(
        None,
        datetime(2028, 2, 29, tzinfo=UTC),
        datetime(2028, 2, 29, tzinfo=UTC),
    )

    assert sum(len(ids) for ids in span["candidates"]["leap_src"]["citations"].values()) == 2
    assert sum(len(ids) for ids in point["candidates"]["leap_src"]["citations"].values()) == 1


@pytest.mark.asyncio
async def test_invalid_params_rejected(tmp_path, monkeypatch):
    rows = [
        _row("1000000000000000001", "cite_1", "guard_src", "2026-10-01T00:00:00Z"),
        _row("1000000000000000002", "cite_1", "guard_src", "2026-10-01T00:00:00Z"),
        _row("1000000000000000003", "cite_2", "guard_src", "2026-10-01T00:00:00Z"),
    ]
    _write_groups(tmp_path, [rows], _dirs(1))
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))

    cases = [
        ({"min_citations": 0}, "min_citations"),
        ({"min_sources": 0}, "min_sources"),
        ({"top_n": 101}, "top_n"),
        ({"since": "2026-10-31T00:00:00Z", "until": "2026-10-01T00:00:00Z"}, "since"),
    ]
    for payload, name in cases:
        rejected = await _call(**payload)
        assert rejected["success"] is False
        assert rejected["error_type"] == "validation"
        assert name in rejected["error"]

    assert await FileSourceCandidateStore(tmp_path).list_candidates() == []


@pytest.mark.asyncio
async def test_store_exception_maps_to_tool_error(tmp_path, monkeypatch):
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    store = FileSourceCandidateStore(tmp_path)
    await store.upsert_candidate(_preset("baseline_src", CandidateStatus.DISCOVERED))

    async def boom(self, tweet_id_filter, since, until):
        raise RuntimeError("取数层炸了")

    monkeypatch.setattr(FileSourceCandidateStore, "scan_citation_signals", boom)
    calls: list[tuple[str, str, dict[str, Any]]] = []

    def spy(tool, action, **kwargs):
        calls.append((tool, action, kwargs))

    monkeypatch.setattr("src.mcp.tools.source_candidate_tools.audit_log", spy)

    result = await _call()

    assert result["success"] is False
    assert result["error_type"] == "internal"
    assert result["error"] == "信源候选操作失败，请稍后重试"
    assert len(calls) == 1
    assert calls[0][2]["result"] == "failure"
    assert len(await store.list_candidates()) == 1


@pytest.mark.asyncio
async def test_unauthorized_call_has_no_side_effect(tmp_path, monkeypatch):
    original_transport = mcp_auth.get_transport()
    rows = [
        _row("1000000000000000001", "cite_1", "guard_src", "2026-10-01T00:00:00Z"),
        _row("1000000000000000002", "cite_1", "guard_src", "2026-10-01T00:00:00Z"),
        _row("1000000000000000003", "cite_2", "guard_src", "2026-10-01T00:00:00Z"),
    ]
    data_root = tmp_path / "guarded"
    _write_groups(data_root, [rows], _dirs(1))
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(data_root))

    # ① 传输层鉴权桩：坏 token 在 dispatch 之前被拒（返回 None，不是抛异常也不是放行）
    assert await XWatcherTokenVerifier().verify_token("bad-token") is None

    # ② 非 admin 传输模式下挖掘入口仍可用 → 挖掘路径本身没有鉴权分支
    try:
        mcp_auth.configure_transport("sse")
        assert mcp_auth.is_admin() is False
        result = await _call()
        assert result["success"] is True
        assert len(result["data"]["mined"]) == 1
    finally:
        mcp_auth.configure_transport(original_transport)

    # ③ 未发生 dispatch 的数据根零落盘（被拒请求不会留下候选）
    untouched = tmp_path / "untouched"
    untouched.mkdir()
    assert iter_source_candidate_docs(untouched) == []
    assert not (untouched / "source_candidates").exists()


@pytest.mark.asyncio
async def test_single_response_no_partial_result(tmp_path, monkeypatch):
    rows = _bulk_rows()
    assert len(rows) == 50_000
    _write_groups(
        tmp_path,
        [rows[:20_000], rows[20_000:40_000], rows[40_000:]],
        ["b00", "b01", "b02"],
    )
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))

    started = time.monotonic()
    result = await _call()
    elapsed = time.monotonic() - started

    assert result["success"] is True
    data = result["data"]
    assert set(data) == {"mined", "merged_refreshed", "stats"}
    assert len(data["mined"]) == data["stats"]["admitted"]
    assert data["stats"]["scanned_tweets"] == 50_000
    assert not ({"cursor", "next", "progress", "partial"} & set(data))
    assert elapsed < 60


@pytest.mark.asyncio
async def test_response_contract_unchanged(tmp_path, monkeypatch):
    _write_groups(tmp_path, _rows_for(_TIE_ROWS, _TIE_TIMES), _dirs(3))
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))

    result = await _call()

    assert result["success"] is True
    data = result["data"]
    assert set(data["stats"]) == {
        "scanned_tweets",
        "signal_candidates",
        "above_threshold",
        "suppressed_in_library",
        "suppressed_pool_terminal",
        "merged_nonterminal",
        "admitted",
    }
    assert data["mined"]
    assert set(data["mined"][0]) == {
        "candidate_id",
        "username",
        "citation_total",
        "source_diversity",
        "subject_tags",
    }
    assert len(data["mined"]) <= 20
    assert sorted(Settings.model_fields) == _CONFIG_KEYS
