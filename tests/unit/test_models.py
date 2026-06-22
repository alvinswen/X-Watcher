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
        # news_items 已作为死表删除,不应再注册
        assert "news_items" not in Base.metadata.tables
    finally:
        engine.dispose()  # 关闭连接
