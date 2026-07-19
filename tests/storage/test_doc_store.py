"""JSON document storage primitive tests."""

from src.storage.doc_store import atomic_write_doc, read_doc


def test_read_doc_returns_none_for_missing_file(tmp_path):
    assert read_doc(tmp_path / "missing.json") is None


def test_atomic_write_doc_round_trips_unicode(tmp_path):
    path = tmp_path / "doc.json"
    document = {"title": "中文标题", "count": 2}

    atomic_write_doc(path, document)

    assert read_doc(path) == document
    assert "中文标题" in path.read_text(encoding="utf-8")


def test_atomic_write_doc_overwrites_existing_document(tmp_path):
    path = tmp_path / "doc.json"
    atomic_write_doc(path, {"version": 1})

    atomic_write_doc(path, {"version": 2})

    assert read_doc(path) == {"version": 2}
