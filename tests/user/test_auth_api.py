"""登录 API (POST /api/auth/login) 测试。"""

import os

import pytest
from httpx import AsyncClient, ASGITransport

from src.config import clear_settings_cache
from src.database.models import Base, User as UserOrm
from src.main import app
from src.user.services.auth_service import AuthService


JWT_SECRET = "test-auth-api-jwt-secret-key-32bytes!"


@pytest.fixture(autouse=True)
def setup_env():
    """设置测试环境变量。"""
    original_jwt = os.environ.get("JWT_SECRET_KEY")
    os.environ["JWT_SECRET_KEY"] = JWT_SECRET
    clear_settings_cache()
    yield
    if original_jwt is None:
        os.environ.pop("JWT_SECRET_KEY", None)
    else:
        os.environ["JWT_SECRET_KEY"] = original_jwt
    clear_settings_cache()


@pytest.fixture
async def test_session():
    """独立的异步数据库会话 fixture，确保 ORM 模型表已创建。"""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_maker() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def client_and_session(test_session):
    """提供 async_client 和 session，覆盖 get_async_session 依赖。"""
    from src.database.async_session import get_async_session

    async def override_get_async_session():
        yield test_session

    app.dependency_overrides[get_async_session] = override_get_async_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, test_session

    app.dependency_overrides.pop(get_async_session, None)


@pytest.fixture
async def seeded_client(client_and_session):
    """创建测试用户并返回 (client, user_email, user_password)。"""
    client, session = client_and_session
    auth_svc = AuthService()

    password = "TestPassword123"
    pw_hash = await auth_svc.hash_password(password)
    user = UserOrm(name="testuser", email="test@example.com", password_hash=pw_hash, is_admin=False)
    session.add(user)
    await session.flush()
    await session.commit()

    return client, "test@example.com", password


@pytest.mark.asyncio
async def test_login_success(seeded_client):
    """正确凭证登录返回 JWT。"""
    client, email, password = seeded_client

    resp = await client.post("/api/auth/login", json={"email": email, "password": password})

    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert len(data["access_token"]) > 0


@pytest.mark.asyncio
async def test_login_wrong_password(seeded_client):
    """错误密码返回 401。"""
    client, email, _ = seeded_client

    resp = await client.post("/api/auth/login", json={"email": email, "password": "WrongPass999"})

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_email(seeded_client):
    """不存在的邮箱返回 401。"""
    client, _, password = seeded_client

    resp = await client.post("/api/auth/login", json={"email": "nobody@example.com", "password": password})

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_jwt_works_for_me_endpoint(seeded_client):
    """登录返回的 JWT 可用于 GET /api/users/me 认证。"""
    client, email, password = seeded_client

    # 先登录获取 JWT
    login_resp = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]

    # 用 JWT 访问 /me
    me_resp = await client.get(
        "/api/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["email"] == email
    assert me_data["name"] == "testuser"
    assert me_data["is_admin"] is False
