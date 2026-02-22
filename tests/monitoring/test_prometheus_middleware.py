"""Prometheus 中间件测试。"""

import pytest

from src.monitoring.middleware import PrometheusMiddleware


class TestNormalizePath:
    """测试路径标准化逻辑。"""

    @pytest.fixture
    def middleware(self):
        """创建中间件实例（无需真实 ASGI app）。"""
        from unittest.mock import MagicMock

        return PrometheusMiddleware(app=MagicMock())

    def test_scrape_task_id_normalized(self, middleware):
        """测试抓取任务 ID 路径被标准化。"""
        result = middleware._normalize_path("/api/admin/scrape/abc123-def")
        assert result == "/api/admin/scrape/{task_id}"

    def test_summary_tweet_id_normalized(self, middleware):
        """测试摘要推文 ID 路径被标准化。"""
        result = middleware._normalize_path("/api/summaries/tweets/tweet-xyz")
        assert result == "/api/summaries/tweets/{tweet_id}"

    def test_summary_task_id_normalized(self, middleware):
        """测试摘要任务 ID 路径被标准化。"""
        result = middleware._normalize_path("/api/summaries/tasks/task-999")
        assert result == "/api/summaries/tasks/{task_id}"

    def test_non_matching_path_unchanged(self, middleware):
        """测试不匹配的路径保持不变。"""
        result = middleware._normalize_path("/api/admin/scrape")
        assert result == "/api/admin/scrape"

    def test_metrics_path_unchanged(self, middleware):
        """测试 /metrics 路径不被修改。"""
        result = middleware._normalize_path("/metrics")
        assert result == "/metrics"

    def test_root_path_unchanged(self, middleware):
        """测试根路径不被修改。"""
        result = middleware._normalize_path("/")
        assert result == "/"

    def test_exact_prefix_without_id_unchanged(self, middleware):
        """测试精确前缀（无 ID 后缀）不被替换。"""
        # /api/admin/scrape/ 本身长度等于前缀，不应替换
        result = middleware._normalize_path("/api/admin/scrape/")
        assert result == "/api/admin/scrape/"

    def test_arbitrary_path_unchanged(self, middleware):
        """测试其他 API 路径保持不变。"""
        result = middleware._normalize_path("/api/feed")
        assert result == "/api/feed"


class TestPrometheusMiddlewareInit:
    """测试中间件初始化。"""

    def test_default_excluded_paths(self):
        """测试默认排除 /metrics 路径。"""
        from unittest.mock import MagicMock

        mw = PrometheusMiddleware(app=MagicMock())
        assert "/metrics" in mw.excluded_paths

    def test_custom_excluded_paths(self):
        """测试自定义排除路径。"""
        from unittest.mock import MagicMock

        mw = PrometheusMiddleware(
            app=MagicMock(),
            excluded_paths=["/health", "/readyz"],
        )
        assert "/health" in mw.excluded_paths
        assert "/readyz" in mw.excluded_paths
        assert "/metrics" not in mw.excluded_paths
