from __future__ import annotations

import pytest

from src.subjects.models import SubjectStatus
from src.subjects.services.classifier import SubjectClassifier
from src.subjects.store import FileSubjectStore


@pytest.mark.asyncio
async def test_prompt_subjects_returns_active_subject_metadata(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject = await repo.create_subject(
        name="OpenAI 发布",
        nl_description="关注 OpenAI 新模型、API 和产品发布",
        keywords=["OpenAI"],
    )

    prompt_subjects = await SubjectClassifier(repo).prompt_subjects()

    assert prompt_subjects == [
        {
            "subject_id": subject.subject_id,
            "name": "OpenAI 发布",
            "nl_description": "关注 OpenAI 新模型、API 和产品发布",
        }
    ]


@pytest.mark.asyncio
async def test_prompt_subjects_omits_paused_subjects(tmp_path):
    repo = FileSubjectStore(tmp_path)
    active = await repo.create_subject(
        name="活跃议题",
        nl_description="后续外部技能可读取这个议题",
    )
    paused = await repo.create_subject(
        name="暂停议题",
        nl_description="暂停议题不进入 prompt 元数据",
        status=SubjectStatus.paused,
    )

    prompt_subjects = await SubjectClassifier(repo).prompt_subjects()

    assert [item["subject_id"] for item in prompt_subjects] == [active.subject_id]
    assert paused.subject_id not in {item["subject_id"] for item in prompt_subjects}
