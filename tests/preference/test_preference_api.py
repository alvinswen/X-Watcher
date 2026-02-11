"""用户偏好 API 集成测试。

测试 PreferenceRouter 端点。
"""

import pytest
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI, status

from src.preference.api.routes import preference_router
from src.preference.infrastructure.preference_repository import PreferenceRepository
from src.preference.infrastructure.scraper_config_repository import ScraperConfigRepository
from src.database.async_session import get_async_session
from src.database.models import User
from src.preference.domain.models import FilterType, SortType
from src.user.api.auth import get_current_user
from src.user.domain.models import UserDomain


class TestPreferenceAPI:
    """测试用户偏好 API 端点。"""

    @pytest.fixture
    def app(self, async_session):
        """创建测试应用。"""
        app = FastAPI()
        app.include_router(preference_router)

        async def get_session_override():
            yield async_session

        app.dependency_overrides[get_async_session] = get_session_override
        yield app
        app.dependency_overrides.clear()

    @pytest.fixture
    async def test_user(self, async_session):
        """创建测试用户。"""
        user = User(name="Test User", email="test@example.com")
        async_session.add(user)
        await async_session.flush()
        return user

    @pytest.fixture
    def mock_auth(self, app, test_user):
        """Mock 认证依赖，返回固定用户。"""
        mock_user = UserDomain(
            id=test_user.id,
            name=test_user.name,
            email=test_user.email,
            is_admin=False,
            created_at=test_user.created_at if test_user.created_at else datetime.now(timezone.utc),
        )

        async def override_get_current_user():
            return mock_user

        app.dependency_overrides[get_current_user] = override_get_current_user
        return mock_user

    @pytest.fixture
    async def client(self, app, mock_auth):
        """创建测试客户端（已 mock 认证）。"""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac

    @pytest.fixture
    async def setup_scraper_follows(self, async_session):
        """准备测试用的抓取账号。"""
        repo = ScraperConfigRepository(async_session)
        await repo.create_scraper_follow("testuser1", "测试账号1", "system")
        await repo.create_scraper_follow("testuser2", "测试账号2", "system")
        await repo.create_scraper_follow("testuser3", "测试账号3", "system")
        await async_session.commit()


class TestFollowManagementAPI(TestPreferenceAPI):
    """测试关注管理 API。"""

    @pytest.mark.asyncio
    async def test_create_follow_success(self, client, test_user, setup_scraper_follows):
        """测试成功创建关注。"""
        request_data = {
            "username": "testuser1",
            "priority": 7
        }

        response = await client.post(
            "/api/preferences/follows",
            json=request_data
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["username"] == "testuser1"
        assert data["priority"] == 7
        assert data["user_id"] == test_user.id

    @pytest.mark.asyncio
    async def test_create_follow_default_priority(self, client, test_user, setup_scraper_follows):
        """测试创建关注时使用默认优先级。"""
        request_data = {"username": "testuser1"}

        response = await client.post(
            "/api/preferences/follows",
            json=request_data
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["priority"] == 5

    @pytest.mark.asyncio
    async def test_create_follow_invalid_username_format(self, client, test_user):
        """测试无效用户名格式返回 422。"""
        request_data = {"username": "invalid@user!"}

        response = await client.post(
            "/api/preferences/follows",
            json=request_data
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @pytest.mark.asyncio
    async def test_create_follow_not_in_scraper_list(self, client, test_user):
        """测试添加不在抓取列表中的账号返回 400。"""
        request_data = {"username": "notinlist"}

        response = await client.post(
            "/api/preferences/follows",
            json=request_data
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "抓取列表" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_follow_duplicate_returns_409(self, client, test_user, setup_scraper_follows, async_session):
        """测试重复创建关注返回 409。"""
        # 创建第一次关注
        repo = PreferenceRepository(async_session)
        await repo.create_follow(test_user.id, "testuser1")
        await async_session.commit()

        # 尝试再次创建
        request_data = {"username": "testuser1"}
        response = await client.post(
            "/api/preferences/follows",
            json=request_data
        )

        assert response.status_code == status.HTTP_409_CONFLICT

    @pytest.mark.asyncio
    async def test_get_follows_success(self, client, test_user, async_session, setup_scraper_follows):
        """测试获取关注列表成功。"""
        repo = PreferenceRepository(async_session)
        await repo.create_follow(test_user.id, "testuser1", priority=8)
        await repo.create_follow(test_user.id, "testuser2", priority=5)
        await async_session.commit()

        response = await client.get(
            "/api/preferences/follows"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 2
        usernames = {item["username"] for item in data}
        assert "testuser1" in usernames
        assert "testuser2" in usernames

    @pytest.mark.asyncio
    async def test_get_follows_with_priority_sort(self, client, test_user, async_session, setup_scraper_follows):
        """测试按优先级排序获取关注列表。"""
        repo = PreferenceRepository(async_session)
        await repo.create_follow(test_user.id, "testuser1", priority=3)
        await repo.create_follow(test_user.id, "testuser2", priority=9)
        await repo.create_follow(test_user.id, "testuser3", priority=5)
        await async_session.commit()

        response = await client.get(
            "/api/preferences/follows?sort=priority"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        # 应该按优先级降序排列
        assert data[0]["username"] == "testuser2"  # priority 9
        assert data[1]["username"] == "testuser3"  # priority 5
        assert data[2]["username"] == "testuser1"  # priority 3

    @pytest.mark.asyncio
    async def test_delete_follow_success(self, client, test_user, async_session, setup_scraper_follows):
        """测试删除关注成功。"""
        repo = PreferenceRepository(async_session)
        await repo.create_follow(test_user.id, "testuser1")
        await async_session.commit()

        response = await client.delete(
            "/api/preferences/follows/testuser1"
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

        # 验证删除
        follow = await repo.get_follow_by_username(test_user.id, "testuser1")
        assert follow is None

    @pytest.mark.asyncio
    async def test_delete_follow_not_found(self, client, test_user):
        """测试删除不存在的关注返回 404。"""
        response = await client.delete(
            "/api/preferences/follows/nonexistent"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_update_priority_success(self, client, test_user, async_session, setup_scraper_follows):
        """测试更新优先级成功。"""
        repo = PreferenceRepository(async_session)
        await repo.create_follow(test_user.id, "testuser1", priority=5)
        await async_session.commit()

        request_data = {"priority": 9}
        response = await client.put(
            "/api/preferences/follows/testuser1/priority",
            json=request_data
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["priority"] == 9

    @pytest.mark.asyncio
    async def test_update_priority_invalid_range(self, client, test_user):
        """测试更新无效优先级返回 422。"""
        request_data = {"priority": 15}  # 超出范围 1-10

        response = await client.put(
            "/api/preferences/follows/testuser1/priority",
            json=request_data
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


class TestFilterManagementAPI(TestPreferenceAPI):
    """测试过滤规则管理 API。"""

    @pytest.mark.asyncio
    async def test_create_keyword_filter_success(self, client, test_user):
        """测试创建关键词过滤规则成功。"""
        request_data = {
            "filter_type": "keyword",
            "value": "spam"
        }

        response = await client.post(
            "/api/preferences/filters",
            json=request_data
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["filter_type"] == FilterType.KEYWORD
        assert data["value"] == "spam"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_create_hashtag_filter_success(self, client, test_user):
        """测试创建话题标签过滤规则成功。"""
        request_data = {
            "filter_type": "hashtag",
            "value": "politics"
        }

        response = await client.post(
            "/api/preferences/filters",
            json=request_data
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["filter_type"] == FilterType.HASHTAG

    @pytest.mark.asyncio
    async def test_create_content_type_filter_success(self, client, test_user):
        """测试创建内容类型过滤规则成功。"""
        request_data = {
            "filter_type": "content_type",
            "value": "retweet"
        }

        response = await client.post(
            "/api/preferences/filters",
            json=request_data
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["filter_type"] == FilterType.CONTENT_TYPE

    @pytest.mark.asyncio
    async def test_get_filters_success(self, client, test_user, async_session):
        """测试获取过滤规则列表成功。"""
        repo = PreferenceRepository(async_session)
        await repo.create_filter(test_user.id, FilterType.KEYWORD, "spam")
        await repo.create_filter(test_user.id, FilterType.HASHTAG, "politics")
        await async_session.commit()

        response = await client.get(
            "/api/preferences/filters"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 2
        values = {item["value"] for item in data}
        assert "spam" in values
        assert "politics" in values

    @pytest.mark.asyncio
    async def test_delete_filter_success(self, client, test_user, async_session):
        """测试删除过滤规则成功。"""
        repo = PreferenceRepository(async_session)
        filter_rule = await repo.create_filter(test_user.id, FilterType.KEYWORD, "spam")
        await async_session.commit()

        response = await client.delete(
            f"/api/preferences/filters/{filter_rule.id}"
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT

    @pytest.mark.asyncio
    async def test_delete_filter_not_found(self, client, test_user):
        """测试删除不存在的过滤规则返回 404。"""
        response = await client.delete(
            "/api/preferences/filters/nonexistent-id"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestSortingPreferenceAPI(TestPreferenceAPI):
    """测试排序偏好 API。"""

    @pytest.mark.asyncio
    async def test_update_sorting_preference_success(self, client, test_user):
        """测试更新排序偏好成功。"""
        request_data = {"sort_type": "relevance"}

        response = await client.put(
            "/api/preferences/sorting",
            json=request_data
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["sort_type"] == SortType.RELEVANCE

    @pytest.mark.asyncio
    async def test_get_sorting_preference_default(self, client, test_user):
        """测试获取默认排序偏好。"""
        response = await client.get(
            "/api/preferences/sorting"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["sort_type"] == SortType.TIME

    @pytest.mark.asyncio
    async def test_get_all_preferences(self, client, test_user, async_session, setup_scraper_follows):
        """测试获取所有偏好配置。"""
        repo = PreferenceRepository(async_session)
        await repo.create_follow(test_user.id, "testuser1", priority=7)
        await repo.create_filter(test_user.id, FilterType.KEYWORD, "spam")
        await repo.set_preference(test_user.id, "sort_type", "relevance")
        await async_session.commit()

        response = await client.get(
            "/api/preferences"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["user_id"] == test_user.id
        assert data["sorting"]["sort_type"] == SortType.RELEVANCE
        assert len(data["follows"]) == 1
        assert len(data["filters"]) == 1


class TestNewsFeedAPI(TestPreferenceAPI):
    """测试个性化新闻流 API。"""

    @pytest.mark.asyncio
    async def test_get_news_by_time_sort(self, client, test_user, async_session, setup_scraper_follows):
        """测试按时间排序获取新闻。"""
        # 初始化用户关注列表
        repo = PreferenceRepository(async_session)
        await repo.batch_create_follows(test_user.id, ["testuser1", "testuser2"])
        await async_session.commit()

        response = await client.get(
            "/api/preferences/news?sort=time&limit=10"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_get_news_by_priority_sort(self, client, test_user, async_session, setup_scraper_follows):
        """测试按优先级排序获取新闻。"""
        repo = PreferenceRepository(async_session)
        await repo.batch_create_follows(test_user.id, ["testuser1", "testuser2"])
        await async_session.commit()

        response = await client.get(
            "/api/preferences/news?sort=priority&limit=10"
        )

        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.json(), list)

    @pytest.mark.asyncio
    async def test_get_news_by_relevance_sort(self, client, test_user, async_session, setup_scraper_follows):
        """测试按相关性排序获取新闻。"""
        repo = PreferenceRepository(async_session)
        await repo.batch_create_follows(test_user.id, ["testuser1", "testuser2"])
        await async_session.commit()

        response = await client.get(
            "/api/preferences/news?sort=relevance&limit=10"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_get_news_applies_filters(self, client, test_user, async_session, setup_scraper_follows):
        """测试新闻流应用过滤规则。"""
        repo = PreferenceRepository(async_session)
        await repo.batch_create_follows(test_user.id, ["testuser1", "testuser2"])
        await repo.create_filter(test_user.id, FilterType.KEYWORD, "test")
        await async_session.commit()

        response = await client.get(
            "/api/preferences/news?sort=time&limit=10"
        )

        assert response.status_code == status.HTTP_200_OK
        assert isinstance(response.json(), list)

    @pytest.mark.asyncio
    async def test_get_news_invalid_sort_type(self, client, test_user):
        """测试无效排序类型返回 422。"""
        response = await client.get(
            "/api/preferences/news?sort=invalid&limit=10"
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @pytest.mark.asyncio
    async def test_get_news_respects_limit(self, client, test_user, async_session, setup_scraper_follows):
        """测试新闻流尊重 limit 参数。"""
        repo = PreferenceRepository(async_session)
        await repo.batch_create_follows(test_user.id, ["testuser1", "testuser2"])
        await async_session.commit()

        response = await client.get(
            "/api/preferences/news?sort=time&limit=5"
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) <= 5
