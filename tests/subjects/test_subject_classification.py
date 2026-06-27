from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from src.subjects.models import SubjectStatus
from src.subjects.services.classifier import SubjectClassifier
from src.subjects.store import FileSubjectStore
from src.summarization.domain.models import PromptConfig, TweetType
from src.summarization.services.summarization_service import SummarizationService


def _summary_service() -> SummarizationService:
    return SummarizationService(session_factory=MagicMock(), providers=[])


@pytest.mark.asyncio
async def test_tc_summ_074_prompt_subjects_parse_and_write_match(tmp_path):
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

    prompt = PromptConfig().format_unified_prompt(
        "OpenAI 发布新的 API 能力",
        TweetType.original,
        is_short=False,
        author_username="openai",
        subjects=prompt_subjects,
    )
    assert "## 议题分类（额外任务）" in prompt
    assert subject.subject_id in prompt
    assert '"subjects"' in prompt

    parsed = _summary_service()._parse_llm_response(
        json.dumps(
            {
                "summary": "OpenAI 发布新的 API 能力。",
                "translation": "OpenAI 发布新的 API 能力。",
                "subjects": [
                    {
                        "subject_id": subject.subject_id,
                        "relevant": True,
                        "relevance": 0.91,
                        "reason": "提到 OpenAI API 发布",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        include_subjects=True,
    )

    summary, translation, raw_subjects = parsed
    assert summary == "OpenAI 发布新的 API 能力。"
    assert translation == "OpenAI 发布新的 API 能力。"
    assert raw_subjects and raw_subjects[0]["subject_id"] == subject.subject_id

    matches = await SubjectClassifier(repo).record_matches("tw_074", raw_subjects)
    assert len(matches) == 1
    assert matches[0].subject_id == subject.subject_id
    assert matches[0].tweet_id == "tw_074"

    stored = await repo.list_matches(subject.subject_id)
    assert [match.tweet_id for match in stored] == ["tw_074"]


@pytest.mark.asyncio
async def test_tc_summ_075_subjects_parse_failure_isolated_from_summary(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject = await repo.create_subject(
        name="AI 安全",
        nl_description="关注 AI safety 与治理讨论",
    )

    summary, translation, raw_subjects = _summary_service()._parse_llm_response(
        '{"summary":"摘要照常可用","translation":"翻译照常可用","subjects":[broken',
        include_subjects=True,
    )

    assert summary == "摘要照常可用"
    assert translation == "翻译照常可用"
    assert raw_subjects is None

    matches = await SubjectClassifier(repo).record_matches("tw_075", raw_subjects)
    assert matches == []
    assert await repo.list_matches(subject.subject_id) == []


def test_tc_summ_076_legacy_schema_without_subjects_returns_none():
    summary, translation, raw_subjects = _summary_service()._parse_llm_response(
        '{"summary":"旧 schema 摘要","translation":"旧 schema 翻译"}',
        include_subjects=True,
    )

    assert summary == "旧 schema 摘要"
    assert translation == "旧 schema 翻译"
    assert raw_subjects is None


@pytest.mark.asyncio
async def test_tc_summ_077_paused_subject_not_prompted_or_classified(tmp_path):
    repo = FileSubjectStore(tmp_path)
    active = await repo.create_subject(
        name="活跃议题",
        nl_description="应该注入并参与新推文分类",
    )
    paused = await repo.create_subject(
        name="暂停议题",
        nl_description="即使命中也不参与新推文分类",
        status=SubjectStatus.paused,
    )

    prompt_subjects = await SubjectClassifier(repo).prompt_subjects()
    assert [item["subject_id"] for item in prompt_subjects] == [active.subject_id]
    assert paused.subject_id not in {item["subject_id"] for item in prompt_subjects}

    raw_subjects = [
        {
            "subject_id": active.subject_id,
            "relevant": True,
            "relevance": 0.9,
            "reason": "active 命中",
        },
        {
            "subject_id": paused.subject_id,
            "relevant": True,
            "relevance": 0.9,
            "reason": "paused 不应落 match",
        },
    ]
    matches = await SubjectClassifier(repo).record_matches("tw_077", raw_subjects)

    assert [match.subject_id for match in matches] == [active.subject_id]
    assert [match.tweet_id for match in await repo.list_matches(active.subject_id)] == ["tw_077"]
    assert await repo.list_matches(paused.subject_id) == []


@pytest.mark.asyncio
async def test_tc_summ_078_multi_label_writes_one_match_per_active_subject(tmp_path):
    repo = FileSubjectStore(tmp_path)
    subject_a = await repo.create_subject(
        name="模型发布",
        nl_description="模型、API 或产品更新",
    )
    subject_b = await repo.create_subject(
        name="开发者生态",
        nl_description="SDK、开发工具或开发者平台",
    )

    raw_subjects = [
        {
            "subject_id": subject_a.subject_id,
            "relevant": True,
            "relevance": 0.88,
            "reason": "模型发布相关",
        },
        {
            "subject_id": subject_b.subject_id,
            "relevant": True,
            "relevance": 0.84,
            "reason": "开发者生态相关",
        },
    ]
    matches = await SubjectClassifier(repo).record_matches("tw_078", raw_subjects)

    assert {match.subject_id for match in matches} == {
        subject_a.subject_id,
        subject_b.subject_id,
    }
    assert [match.tweet_id for match in await repo.list_matches(subject_a.subject_id)] == ["tw_078"]
    assert [match.tweet_id for match in await repo.list_matches(subject_b.subject_id)] == ["tw_078"]


@pytest.mark.asyncio
async def test_tc_summ_079_no_active_subjects_omits_classification_prompt(tmp_path):
    repo = FileSubjectStore(tmp_path)
    await repo.create_subject(
        name="暂停议题",
        nl_description="没有 active 议题时不注入分类段",
        status=SubjectStatus.paused,
    )

    prompt_subjects = await SubjectClassifier(repo).prompt_subjects()
    assert prompt_subjects == []

    prompt = PromptConfig().format_unified_prompt(
        "A normal product update",
        TweetType.original,
        is_short=False,
        subjects=prompt_subjects,
    )
    assert "## 议题分类（额外任务）" not in prompt
    assert '"subjects"' not in prompt

    summary, translation, raw_subjects = _summary_service()._parse_llm_response(
        '{"summary":"摘要","translation":"翻译"}',
        include_subjects=True,
    )
    assert summary == "摘要"
    assert translation == "翻译"
    assert raw_subjects is None
    assert await SubjectClassifier(repo).record_matches("tw_079", raw_subjects) == []
