# src/summarization/infrastructure/summary_store.py
"""摘要仓库异常定义(文件层实现见 file_summary_repository.py)。"""

from __future__ import annotations


class RepositoryError(Exception):
    """仓库操作错误。"""
