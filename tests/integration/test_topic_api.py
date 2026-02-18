"""主题管理 API 集成测试。

使用 async_client fixture（已配置管理员认证和测试数据库）。
"""

import pytest
from httpx import AsyncClient

from src.database.models import ScraperFollow


# ── 辅助函数 ──


async def _create_scraper_follow(session, username: str):
    """创建 scraper_follow 记录。"""
    follow = ScraperFollow(
        username=username, reason="test", added_by="test", is_active=True
    )
    session.add(follow)
    await session.flush()


# ── 主题 CRUD 完整流程测试 ──


@pytest.mark.asyncio
async def test_topic_crud_flow(async_client: AsyncClient, async_session):
    """测试主题 CRUD 完整流程。"""
    # 创建
    resp = await async_client.post(
        "/api/topics", json={"name": "AI产品", "description": "测试"}
    )
    assert resp.status_code == 201
    data = resp.json()
    topic_id = data["id"]
    assert data["name"] == "AI产品"
    assert data["description"] == "测试"
    assert "created_at" in data
    assert "updated_at" in data

    # 列表
    resp = await async_client.get("/api/topics")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["name"] == "AI产品"
    assert items[0]["account_count"] == 0

    # 详情
    resp = await async_client.get(f"/api/topics/{topic_id}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["name"] == "AI产品"
    assert detail["accounts"] == []

    # 更新
    resp = await async_client.put(
        f"/api/topics/{topic_id}", json={"name": "AI产品v2"}
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "AI产品v2"

    # 删除
    resp = await async_client.delete(f"/api/topics/{topic_id}")
    assert resp.status_code == 204

    # 删除不存在的
    resp = await async_client.delete(f"/api/topics/{topic_id}")
    assert resp.status_code == 404


# ── 账号管理端点测试 ──


@pytest.mark.asyncio
async def test_account_management_flow(async_client: AsyncClient, async_session):
    """测试账号管理端点：添加 → 批量替换 → 删除。"""
    # 创建 scraper_follows
    await _create_scraper_follow(async_session, "user_a")
    await _create_scraper_follow(async_session, "user_b")
    await _create_scraper_follow(async_session, "user_c")
    await async_session.commit()

    # 创建主题
    resp = await async_client.post(
        "/api/topics", json={"name": "账号管理测试"}
    )
    assert resp.status_code == 201
    topic_id = resp.json()["id"]

    # 添加账号
    resp = await async_client.post(
        f"/api/topics/{topic_id}/accounts/user_a"
    )
    assert resp.status_code == 201
    assert resp.json()["username"] == "user_a"

    # 验证详情中有该账号
    resp = await async_client.get(f"/api/topics/{topic_id}")
    assert resp.status_code == 200
    assert len(resp.json()["accounts"]) == 1

    # 批量替换
    resp = await async_client.put(
        f"/api/topics/{topic_id}/accounts",
        json={"usernames": ["user_b", "user_c"]},
    )
    assert resp.status_code == 200
    accounts = resp.json()
    assert len(accounts) == 2
    usernames = {a["username"] for a in accounts}
    assert usernames == {"user_b", "user_c"}

    # 删除账号
    resp = await async_client.delete(
        f"/api/topics/{topic_id}/accounts/user_b"
    )
    assert resp.status_code == 204

    # 验证只剩一个账号
    resp = await async_client.get(f"/api/topics/{topic_id}")
    assert len(resp.json()["accounts"]) == 1
    assert resp.json()["accounts"][0]["username"] == "user_c"


# ── 错误场景测试 ──


@pytest.mark.asyncio
async def test_create_topic_duplicate_name_409(async_client: AsyncClient, async_session):
    """名称重复返回 409。"""
    await async_client.post(
        "/api/topics", json={"name": "重复名称"}
    )
    resp = await async_client.post(
        "/api/topics", json={"name": "重复名称"}
    )
    assert resp.status_code == 409
    assert "已存在" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_get_topic_not_found_404(async_client: AsyncClient, async_session):
    """主题不存在返回 404。"""
    resp = await async_client.get("/api/topics/9999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_topic_not_found_404(async_client: AsyncClient, async_session):
    """更新不存在的主题返回 404。"""
    resp = await async_client.put(
        "/api/topics/9999", json={"name": "不存在"}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_topic_duplicate_name_409(async_client: AsyncClient, async_session):
    """更新主题名称重复返回 409。"""
    await async_client.post("/api/topics", json={"name": "名称A"})
    resp2 = await async_client.post("/api/topics", json={"name": "名称B"})
    topic_b_id = resp2.json()["id"]

    resp = await async_client.put(
        f"/api/topics/{topic_b_id}", json={"name": "名称A"}
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_add_account_not_in_scraper_follows_400(
    async_client: AsyncClient, async_session
):
    """账号不在 scraper_follows 中返回 400。"""
    resp = await async_client.post(
        "/api/topics", json={"name": "验证测试"}
    )
    topic_id = resp.json()["id"]

    resp = await async_client.post(
        f"/api/topics/{topic_id}/accounts/nonexistent"
    )
    assert resp.status_code == 400
    assert "未在系统抓取列表中注册" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_add_account_duplicate_409(async_client: AsyncClient, async_session):
    """账号已关联返回 409。"""
    await _create_scraper_follow(async_session, "dup_user")
    await async_session.commit()

    resp = await async_client.post(
        "/api/topics", json={"name": "重复账号测试"}
    )
    topic_id = resp.json()["id"]

    await async_client.post(
        f"/api/topics/{topic_id}/accounts/dup_user"
    )
    resp = await async_client.post(
        f"/api/topics/{topic_id}/accounts/dup_user"
    )
    assert resp.status_code == 409
    assert "已关联" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_add_account_topic_not_found_404(
    async_client: AsyncClient, async_session
):
    """向不存在的主题添加账号返回 404。"""
    resp = await async_client.post(
        "/api/topics/9999/accounts/someuser"
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_remove_account_not_found_404(
    async_client: AsyncClient, async_session
):
    """移除不存在的账号返回 404。"""
    resp = await async_client.post(
        "/api/topics", json={"name": "移除测试"}
    )
    topic_id = resp.json()["id"]

    resp = await async_client.delete(
        f"/api/topics/{topic_id}/accounts/not_found"
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_set_accounts_topic_not_found_404(
    async_client: AsyncClient, async_session
):
    """批量设置账号时主题不存在返回 404。"""
    resp = await async_client.put(
        "/api/topics/9999/accounts",
        json={"usernames": ["user1"]},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_set_accounts_invalid_username_400(
    async_client: AsyncClient, async_session
):
    """批量设置账号时用户名无效返回 400。"""
    resp = await async_client.post(
        "/api/topics", json={"name": "批量验证测试"}
    )
    topic_id = resp.json()["id"]

    resp = await async_client.put(
        f"/api/topics/{topic_id}/accounts",
        json={"usernames": ["invalid_user"]},
    )
    assert resp.status_code == 400
    assert "未在系统抓取列表中注册" in resp.json()["detail"]
