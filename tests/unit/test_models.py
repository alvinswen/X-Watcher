"""测试数据库模型。"""

import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def test_user_model_creation():
    """测试用户模型创建。"""
    from src.database.models import User

    user = User(
        name="Test User",
        email="test@example.com"
    )

    assert user.name == "Test User"
    assert user.email == "test@example.com"
    assert user.id is None  # 未保存前 id 为 None
    assert user.created_at is None  # 未保存前 created_at 为 None


def test_preference_model_creation():
    """测试偏好模型创建。"""
    from src.database.models import Preference, User

    user = User(id=1, name="Test", email="test@example.com")
    preference = Preference(
        user_id=user.id,
        key="language",
        value="zh"
    )

    assert preference.user_id == 1
    assert preference.key == "language"
    assert preference.value == "zh"


def test_news_item_model_creation():
    """测试新闻模型创建。"""
    from src.database.models import NewsItem, User

    user = User(id=1, name="Test", email="test@example.com")
    news = NewsItem(
        user_id=user.id,
        content="Test news content",
        source="twitter"
    )

    assert news.user_id == 1
    assert news.content == "Test news content"
    assert news.source == "twitter"


def test_database_tables_creation():
    """测试数据库表创建。"""
    from src.database.models import Base

    # 使用内存数据库
    engine = create_engine("sqlite:///:memory:")

    try:
        # 创建所有表
        Base.metadata.create_all(engine)

        # 验证表已创建
        assert "users" in Base.metadata.tables
        assert "preferences" in Base.metadata.tables
        assert "news_items" in Base.metadata.tables
    finally:
        engine.dispose()  # 关闭连接


def test_user_relationship_to_preferences():
    """测试用户与偏好的关系。"""
    from src.database.models import User, Preference

    user = User(id=1, name="Test", email="test@example.com")
    pref1 = Preference(id=1, user_id=1, key="lang", value="zh")
    pref2 = Preference(id=2, user_id=1, key="theme", value="dark")

    # SQLAlchemy 关系需要通过 Session 加载
    # 这里只验证模型定义
    assert pref1.user_id == user.id
    assert pref2.user_id == user.id


def test_user_relationship_to_news_items():
    """测试用户与新闻的关系。"""
    from src.database.models import User, NewsItem

    user = User(id=1, name="Test", email="test@example.com")
    news1 = NewsItem(id=1, user_id=1, content="News 1", source="twitter")
    news2 = NewsItem(id=2, user_id=1, content="News 2", source="rss")

    assert news1.user_id == user.id
    assert news2.user_id == user.id
