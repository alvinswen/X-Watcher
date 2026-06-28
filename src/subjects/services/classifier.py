"""Subject 在线分类接入。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from src.data_layer.provider import get_subject_repo


class SubjectClassifier:
    """提供议题 prompt 元数据，供后续外部技能复用。"""

    def __init__(self, repo: Any | None = None) -> None:
        repo_factory = cast(Callable[[], Any], get_subject_repo)
        self._repo: Any = repo if repo is not None else repo_factory()

    async def prompt_subjects(self) -> list[dict[str, str]]:
        subjects = (await self._repo.list_active_subjects())[:20]
        return [
            {
                "subject_id": subject.subject_id,
                "name": subject.name,
                "nl_description": subject.nl_description,
            }
            for subject in subjects
        ]
