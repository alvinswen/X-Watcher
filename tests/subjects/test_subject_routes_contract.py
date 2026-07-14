from __future__ import annotations

import pytest

from src.subjects.constants import MAX_ACTIVE_SUBJECTS
from src.subjects.store import FileSubjectStore


@pytest.mark.asyncio
async def test_missing_subject_rest_detail_is_stable(async_client, tmp_path, monkeypatch):
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))

    response = await async_client.get("/api/admin/subjects/sub_missing")

    assert response.status_code == 404
    assert response.json() == {"detail": "议题不存在"}


@pytest.mark.asyncio
async def test_active_subject_limit_rest_detail_is_stable(async_client, tmp_path, monkeypatch):
    monkeypatch.setenv("XWATCHER_DATA_ROOT", str(tmp_path))
    repo = FileSubjectStore(tmp_path)
    for index in range(MAX_ACTIVE_SUBJECTS):
        await repo.create_subject(
            name=f"议题 {index}",
            nl_description="达到活跃议题上限的运行时契约守卫",
        )

    response = await async_client.post(
        "/api/admin/subjects",
        json={"name": "超额议题", "nl_description": "不应创建"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "已达议题上限，先停用旧议题"}
