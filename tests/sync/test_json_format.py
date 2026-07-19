"""JSON 格式读写测试。"""

import json
from datetime import UTC, datetime

import pytest

from src.sync.domain.models import ExportFilters, ExportMetadata, ExportPackage
from src.sync.format.json_format import read_export_file, write_export_file


def _make_package(**overrides) -> ExportPackage:
    """创建测试用 ExportPackage。"""
    meta = ExportMetadata(
        exported_at=datetime(2026, 2, 24, 12, 0, 0, tzinfo=UTC),
        source_instance_id="test-server",
        categories=["config"],
        counts={"scraper_follows": 2},
    )
    data = {
        "config": {
            "scraper_follows": [
                {"username": "alice", "is_active": True},
            ],
        },
    }
    defaults = {"metadata": meta, "data": data}
    defaults.update(overrides)
    return ExportPackage(**defaults)


class TestWriteAndRead:
    """写入后重新读取应产生等价数据。"""

    def test_roundtrip(self, tmp_path):
        pkg = _make_package()
        path = tmp_path / "export.json"
        write_export_file(pkg, path)
        loaded = read_export_file(path)

        assert loaded.metadata.format_version == "1.0"
        assert loaded.metadata.schema_version == 1
        assert loaded.metadata.source_instance_id == "test-server"
        assert loaded.metadata.categories == ["config"]
        assert loaded.metadata.counts["scraper_follows"] == 2
        assert loaded.data["config"]["scraper_follows"][0]["username"] == "alice"

    def test_pretty_output(self, tmp_path):
        pkg = _make_package()
        path = tmp_path / "pretty.json"
        write_export_file(pkg, path, pretty=True)
        content = path.read_text(encoding="utf-8")
        # Pretty 模式下应包含缩进
        assert "\n  " in content

    def test_compact_output(self, tmp_path):
        pkg = _make_package()
        path = tmp_path / "compact.json"
        write_export_file(pkg, path, pretty=False)
        content = path.read_text(encoding="utf-8")
        # Compact 模式下不应有缩进换行（除了内容本身）
        lines = content.strip().split("\n")
        assert len(lines) == 1

    def test_filters_roundtrip(self, tmp_path):
        meta = ExportMetadata(
            exported_at=datetime(2026, 2, 24, tzinfo=UTC),
            source_instance_id="s1",
            categories=["content"],
            filters=ExportFilters(
                since=datetime(2026, 1, 1, tzinfo=UTC),
                authors=["alice", "bob"],
            ),
        )
        pkg = ExportPackage(metadata=meta, data={"content": {"tweets": []}})
        path = tmp_path / "filtered.json"
        write_export_file(pkg, path)
        loaded = read_export_file(path)

        assert loaded.metadata.filters.authors == ["alice", "bob"]
        assert loaded.metadata.filters.since is not None
        assert loaded.metadata.filters.until is None


class TestReadValidation:
    """读取时的校验逻辑。"""

    def test_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_export_file(tmp_path / "nonexistent.json")

    def test_invalid_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            read_export_file(path)

    def test_not_object(self, tmp_path):
        path = tmp_path / "array.json"
        path.write_text("[]", encoding="utf-8")
        with pytest.raises(ValueError, match="顶层必须是 JSON 对象"):
            read_export_file(path)

    def test_missing_metadata(self, tmp_path):
        path = tmp_path / "no_meta.json"
        path.write_text('{"data": {}}', encoding="utf-8")
        with pytest.raises(ValueError, match="缺少 metadata"):
            read_export_file(path)

    def test_missing_data(self, tmp_path):
        path = tmp_path / "no_data.json"
        path.write_text(
            json.dumps({
                "metadata": {
                    "exported_at": "2026-01-01T00:00:00+00:00",
                    "source_instance_id": "x",
                },
            }),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="缺少 data"):
            read_export_file(path)

    def test_schema_version_too_high(self, tmp_path):
        path = tmp_path / "future.json"
        path.write_text(
            json.dumps({
                "metadata": {
                    "schema_version": 999,
                    "exported_at": "2026-01-01T00:00:00+00:00",
                    "source_instance_id": "x",
                },
                "data": {},
            }),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="schema 版本不兼容"):
            read_export_file(path)

    def test_force_skips_version_check(self, tmp_path):
        path = tmp_path / "future.json"
        path.write_text(
            json.dumps({
                "metadata": {
                    "schema_version": 999,
                    "exported_at": "2026-01-01T00:00:00+00:00",
                    "source_instance_id": "x",
                    "categories": [],
                },
                "data": {},
            }),
            encoding="utf-8",
        )
        pkg = read_export_file(path, force=True)
        assert pkg.metadata.schema_version == 999
