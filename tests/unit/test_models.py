"""测试数据库模型。"""

from sqlalchemy import create_engine


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
        assert "news_items" in Base.metadata.tables
    finally:
        engine.dispose()  # 关闭连接


def test_user_relationship_to_news_items():
    """测试用户与新闻的关系。"""
    from src.database.models import User, NewsItem

    user = User(id=1, name="Test", email="test@example.com")
    news1 = NewsItem(id=1, user_id=1, content="News 1", source="twitter")
    news2 = NewsItem(id=2, user_id=1, content="News 2", source="rss")

    assert news1.user_id == user.id
    assert news2.user_id == user.id
