"""Prometheus 中间件测试。"""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.monitoring import middleware as middleware_module
from src.monitoring.middleware import PrometheusMiddleware


class TestRoutePathLabel:
    """测试真实路由匹配后的指标路径标签。"""

    @pytest.fixture
    def client(self, monkeypatch):
        requests = MagicMock()
        durations = MagicMock()
        monkeypatch.setattr(middleware_module.metrics, "http_requests_total", requests)
        monkeypatch.setattr(middleware_module.metrics, "http_request_duration_seconds", durations)

        app = FastAPI()
        app.add_middleware(PrometheusMiddleware)

        @app.get("/")
        def root():
            return {"ok": True}

        @app.get("/api/items")
        def list_items():
            return []

        @app.get("/api/items/{item_id}")
        def get_item(item_id: str):
            return {"id": item_id}

        @app.post("/api/jobs/{job_id}/runs/{run_id}")
        def run_job(job_id: str, run_id: str):
            return {"job_id": job_id, "run_id": run_id}

        @app.get("/metrics")
        def metrics_route():
            return "excluded"

        return TestClient(app), requests, durations

    def test_dynamic_get_uses_route_template(self, client):
        test_client, requests, _ = client
        assert test_client.get("/api/items/abc123").status_code == 200
        requests.labels.assert_called_once_with(method="GET", path="/api/items/{item_id}", status="200")

    def test_different_params_share_one_template(self, client):
        test_client, requests, _ = client
        test_client.get("/api/items/one")
        test_client.get("/api/items/two")
        assert {call.kwargs["path"] for call in requests.labels.call_args_list} == {"/api/items/{item_id}"}

    def test_multiple_dynamic_segments_use_template(self, client):
        test_client, requests, _ = client
        assert test_client.post("/api/jobs/job-1/runs/run-9").status_code == 200
        requests.labels.assert_called_once_with(
            method="POST", path="/api/jobs/{job_id}/runs/{run_id}", status="200"
        )

    def test_static_route_uses_declared_path(self, client):
        test_client, requests, _ = client
        assert test_client.get("/api/items").status_code == 200
        requests.labels.assert_called_once_with(method="GET", path="/api/items", status="200")

    def test_root_route_uses_declared_path(self, client):
        test_client, requests, _ = client
        assert test_client.get("/").status_code == 200
        requests.labels.assert_called_once_with(method="GET", path="/", status="200")

    def test_unmatched_route_uses_bounded_fallback(self, client):
        test_client, requests, _ = client
        assert test_client.get("/does/not/exist/123").status_code == 404
        requests.labels.assert_called_once_with(method="GET", path="__unmatched__", status="404")

    def test_duration_uses_same_route_template(self, client):
        test_client, _, durations = client
        test_client.get("/api/items/abc123")
        durations.labels.assert_called_once_with(method="GET", path="/api/items/{item_id}")

    def test_excluded_path_is_not_recorded(self, client):
        test_client, requests, durations = client
        assert test_client.get("/metrics").status_code == 200
        requests.labels.assert_not_called()
        durations.labels.assert_not_called()


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
