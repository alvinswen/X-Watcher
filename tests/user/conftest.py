"""Shared user API test fixtures."""

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app


@pytest.fixture(autouse=True)
def _isolate_login_rate_limiter():
    """隔离登录限流器全实例单闸状态（CHG-041 · CHG-039 熔断器隔离范式）。"""
    from src.user.services.login_rate_limiter import login_rate_limiter as rl

    prev = (rl._failure_count, rl._locked_until, rl.clock)
    rl.reset()
    yield
    rl._failure_count, rl._locked_until, rl.clock = prev


@pytest.fixture
async def client_and_session():
    """提供 async_client 和 session。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, None
