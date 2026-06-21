"""TopicService 单元测试。

测试主题管理业务服务的完整 CRUD 操作和账号管理。
"""

import pytest

from src.database.models import ScraperFollow
from src.topic.services.topic_service import TopicService


@pytest.fixture(autouse=True)
def _pin_sqlalchemy_layer(monkeypatch):
    """钉 sqlalchemy 模式:本组是行为保真回归(走真 session),不受本地 .env 的
    XWATCHER_DATA_LAYER=file 污染(否则 service 经 provider 切到文件层、读到 data_root
    持久数据 → 跨测试状态泄漏)。file 模式覆盖见 tests/data_layer/test_topic_service_file_mode.py。"""
    monkeypatch.setenv("XWATCHER_DATA_LAYER", "sqlalchemy")


# ── 辅助函数 ──


async def _create_scraper_follow(session, username: str):
    """创建 scraper_follow 记录。"""
    follow = ScraperFollow(
        username=username,
        reason="test",
        added_by="test",
        is_active=True,
    )
    session.add(follow)
    await session.flush()
    return follow


@pytest.fixture
def service() -> TopicService:
    return TopicService()


# ── 主题 CRUD 测试 ──


@pytest.mark.asyncio
async def test_create_topic(async_session, service):
    """创建主题正常流程。"""
    topic = await service.create_topic(async_session, "AI产品", "测试描述")
    assert topic.id is not None
    assert topic.name == "AI产品"
    assert topic.description == "测试描述"
    assert topic.created_at is not None
    assert topic.updated_at is not None


@pytest.mark.asyncio
async def test_create_topic_duplicate_name(async_session, service):
    """创建主题名称重复时报错。"""
    await service.create_topic(async_session, "重复名称", "描述1")
    with pytest.raises(ValueError, match="已存在"):
        await service.create_topic(async_session, "重复名称", "描述2")


@pytest.mark.asyncio
async def test_list_topics(async_session, service):
    """列表查询返回正确的账号数量。"""
    await service.create_topic(async_session, "主题A")
    await service.create_topic(async_session, "主题B")

    topics = await service.list_topics(async_session)
    assert len(topics) == 2
    # 按创建时间倒序
    assert topics[0].name == "主题B"
    assert topics[1].name == "主题A"
    # 没有关联账号时 account_count 为 0
    assert topics[0].account_count == 0


@pytest.mark.asyncio
async def test_list_topics_with_account_count(async_session, service):
    """列表查询返回正确的关联账号数量。"""
    topic = await service.create_topic(async_session, "测试主题")

    # 先创建 scraper_follows
    await _create_scraper_follow(async_session, "user1")
    await _create_scraper_follow(async_session, "user2")

    await service.add_account(async_session, topic.id, "user1")
    await service.add_account(async_session, topic.id, "user2")

    topics = await service.list_topics(async_session)
    assert len(topics) == 1
    assert topics[0].account_count == 2


@pytest.mark.asyncio
async def test_get_topic_detail(async_session, service):
    """详情查询返回账号列表。"""
    topic = await service.create_topic(async_session, "详情测试")

    # 添加账号
    await _create_scraper_follow(async_session, "detail_user")
    await service.add_account(async_session, topic.id, "detail_user")

    detail = await service.get_topic(async_session, topic.id)
    assert detail is not None
    assert detail.name == "详情测试"
    assert len(detail.accounts) == 1
    assert detail.accounts[0].username == "detail_user"


@pytest.mark.asyncio
async def test_get_topic_not_found(async_session, service):
    """查询不存在的主题返回 None。"""
    detail = await service.get_topic(async_session, 9999)
    assert detail is None


@pytest.mark.asyncio
async def test_update_topic(async_session, service):
    """更新主题正常流程。"""
    topic = await service.create_topic(async_session, "原始名称", "原始描述")

    updated = await service.update_topic(async_session, topic.id, name="新名称", description="新描述")
    assert updated is not None
    assert updated.name == "新名称"
    assert updated.description == "新描述"


@pytest.mark.asyncio
async def test_update_topic_duplicate_name(async_session, service):
    """更新主题名称重复时报错。"""
    await service.create_topic(async_session, "名称A")
    topic_b = await service.create_topic(async_session, "名称B")

    with pytest.raises(ValueError, match="已存在"):
        await service.update_topic(async_session, topic_b.id, name="名称A")


@pytest.mark.asyncio
async def test_update_topic_not_found(async_session, service):
    """更新不存在的主题返回 None。"""
    result = await service.update_topic(async_session, 9999, name="不存在")
    assert result is None


@pytest.mark.asyncio
async def test_update_topic_same_name(async_session, service):
    """更新主题时名称不变不报错。"""
    topic = await service.create_topic(async_session, "不变名称")
    updated = await service.update_topic(async_session, topic.id, name="不变名称", description="改描述")
    assert updated is not None
    assert updated.name == "不变名称"
    assert updated.description == "改描述"


@pytest.mark.asyncio
async def test_delete_topic(async_session, service):
    """删除主题成功。"""
    topic = await service.create_topic(async_session, "待删除")
    result = await service.delete_topic(async_session, topic.id)
    assert result is True

    # 验证已删除
    detail = await service.get_topic(async_session, topic.id)
    assert detail is None


@pytest.mark.asyncio
async def test_delete_topic_not_found(async_session, service):
    """删除不存在的主题返回 False。"""
    result = await service.delete_topic(async_session, 9999)
    assert result is False


# ── 账号管理测试 ──


@pytest.mark.asyncio
async def test_add_account(async_session, service):
    """添加账号正常流程。"""
    topic = await service.create_topic(async_session, "账号测试")
    await _create_scraper_follow(async_session, "testuser")

    account = await service.add_account(async_session, topic.id, "testuser")
    assert account.username == "testuser"
    assert account.topic_id == topic.id
    assert account.added_at is not None


@pytest.mark.asyncio
async def test_add_account_username_not_in_scraper_follows(async_session, service):
    """添加账号时 username 不在 scraper_follows 中时报错。"""
    topic = await service.create_topic(async_session, "验证测试")

    with pytest.raises(ValueError, match="未在系统抓取列表中注册"):
        await service.add_account(async_session, topic.id, "nonexistent")


@pytest.mark.asyncio
async def test_add_account_topic_not_found(async_session, service):
    """添加账号到不存在的主题时报错。"""
    with pytest.raises(ValueError, match="不存在"):
        await service.add_account(async_session, 9999, "testuser")


@pytest.mark.asyncio
async def test_add_account_duplicate(async_session, service):
    """添加已存在的账号时报错。"""
    topic = await service.create_topic(async_session, "重复账号测试")
    await _create_scraper_follow(async_session, "dupuser")

    await service.add_account(async_session, topic.id, "dupuser")
    with pytest.raises(ValueError, match="已关联"):
        await service.add_account(async_session, topic.id, "dupuser")


@pytest.mark.asyncio
async def test_remove_account(async_session, service):
    """移除账号。"""
    topic = await service.create_topic(async_session, "移除测试")
    await _create_scraper_follow(async_session, "removeuser")
    await service.add_account(async_session, topic.id, "removeuser")

    result = await service.remove_account(async_session, topic.id, "removeuser")
    assert result is True


@pytest.mark.asyncio
async def test_remove_account_not_found(async_session, service):
    """移除不存在的账号返回 False。"""
    topic = await service.create_topic(async_session, "移除不存在测试")
    result = await service.remove_account(async_session, topic.id, "notfound")
    assert result is False


@pytest.mark.asyncio
async def test_set_accounts(async_session, service):
    """批量替换账号。"""
    topic = await service.create_topic(async_session, "批量测试")
    await _create_scraper_follow(async_session, "old_a")
    await _create_scraper_follow(async_session, "new_x")
    await _create_scraper_follow(async_session, "new_y")

    # 先添加旧账号
    await service.add_account(async_session, topic.id, "old_a")

    # 批量替换
    accounts = await service.set_accounts(async_session, topic.id, ["new_x", "new_y"])
    assert len(accounts) == 2
    usernames = {a.username for a in accounts}
    assert usernames == {"new_x", "new_y"}

    # 验证详情中只有新账号
    detail = await service.get_topic(async_session, topic.id)
    detail_usernames = {a.username for a in detail.accounts}
    assert detail_usernames == {"new_x", "new_y"}


@pytest.mark.asyncio
async def test_set_accounts_topic_not_found(async_session, service):
    """批量替换账号时主题不存在报错。"""
    with pytest.raises(ValueError, match="不存在"):
        await service.set_accounts(async_session, 9999, ["user1"])


@pytest.mark.asyncio
async def test_set_accounts_invalid_username(async_session, service):
    """批量替换账号时用户名不在 scraper_follows 中报错。"""
    topic = await service.create_topic(async_session, "验证批量测试")

    with pytest.raises(ValueError, match="未在系统抓取列表中注册"):
        await service.set_accounts(async_session, topic.id, ["invalid_user"])
