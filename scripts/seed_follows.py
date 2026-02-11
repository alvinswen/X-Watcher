#!/usr/bin/env python
"""批量导入关注账号脚本。

将首批 Twitter 关注账号导入 scraper_follows 表。
"""

from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.database.models import ScraperFollow, get_engine

# 首批 50 个关注账号：(username, reason)
INITIAL_FOLLOWS = [
    ("sama", "OpenAI CEO；AI行业风向标"),
    ("gdb", "OpenAI主席；技术决策核心"),
    ("karpathy", "AI教育先驱；vibe coding创始人"),
    ("ilyasut", "AI安全权威；前OpenAI首席科学家"),
    ("DarioAmodei", "Anthropic CEO；Claude创造者"),
    ("demishassabis", "DeepMind CEO；诺贝尔奖得主"),
    ("ylecun", "Meta首席AI科学家；图灵奖得主"),
    ("elonmusk", "xAI创始人；X平台拥有者"),
    ("btaylor", "Sierra AI CEO；企业Agent标杆"),
    ("ID_AA_Carmack", "AGI研发；传奇程序员"),
    ("AndrewYNg", "DeepLearning.AI创始人；AI教育普及"),
    ("drfeifei", "Stanford HAI主任；AI教母"),
    ("fchollet", "Keras创建者；ARC-AGI发起人"),
    ("lexfridman", "MIT研究员；顶级AI播客"),
    ("jeremyphoward", "fast.ai创始人；实用AI教育"),
    ("DrJimFan", "NVIDIA研究员；具身AI专家"),
    ("AlecRad", "OpenAI研究员；CLIP核心作者"),
    ("GaryMarcus", "NYU教授；AI批判性思考者"),
    ("ESYudkowsky", "MIRI联合创始人；AI安全倡导"),
    ("katecrawford", "AI伦理权威；Atlas of AI作者"),
    ("truellmichael", "Cursor CEO；AI编程工具领军者"),
    ("sualeh_asif", "Cursor CPO；产品视觉负责人"),
    ("arvidlunnemark", "Cursor前CTO；系统架构专家"),
    ("amansanger", "Cursor COO；运营策略专家"),
    ("amasad", "Replit CEO；vibe coding先锋"),
    ("ashtom", "GitHub CEO；Copilot推动者"),
    ("alexalbert__", "Claude产品负责人；影响Claude Code"),
    ("hwchase17", "LangChain创始人；Agent框架开创者"),
    ("yoheinakajima", "BabyAGI创始人；自主Agent先驱"),
    ("ShishirPatil_", "伯克利AI研究员；Gorilla LLM"),
    ("divgarg9", "MultiOn创始人；浏览器Agent先驱"),
    ("joshalbrecht", "Imbue创始人；长期推理Agent"),
    ("Altimor", "Lindy.ai创始人；个人AI助手"),
    ("ShunyuYao12", "Princeton博士；ReAct论文作者"),
    ("dennyzhou", "Google DeepMind；CoT研究员"),
    ("lateinteraction", "DSPy创建者；提示工程自动化"),
    ("jerryjliu0", "LlamaIndex创始人；RAG框架先驱"),
    ("luisvonahn", "Duolingo CEO；AI-first教育转型"),
    ("severinhacker", "Duolingo CTO；技术架构核心"),
    ("khanacademy", "Khan Academy创始人；AI导师"),
    ("quaesita", "Google决策科学家；AI教育布道者"),
    ("mrdbourke", "YouTube AI教育；实用机器学习"),
    ("3blue1brown", "数学可视化大师；神经网络教学经典"),
    ("levelsio", "独立开发者鼻祖；完全透明分享"),
    ("dannypostmaa", "AI工具变现专家；SEO大师"),
    ("marc_louvion", "ShipFast创建者；快速MVP专家"),
    ("rowancheung", "The Rundown创始人；AI资讯聚合"),
    ("VarunMayya", "Avalon Labs CEO；印度顶级创业者"),
    ("spolu", "Dust.tt创始人；企业AI助手平台"),
    ("tdinh_me", "多产品独立开发者；工具创建者"),
]


def seed_follows() -> None:
    """批量导入关注账号到 scraper_follows 表。

    自动跳过已存在的用户名。
    """
    engine = get_engine()

    success_count = 0
    skipped_count = 0
    failed_count = 0

    with Session(engine) as session:
        print("=" * 60)
        print(f"开始导入 {len(INITIAL_FOLLOWS)} 个关注账号")
        print("=" * 60)

        for username, reason in INITIAL_FOLLOWS:
            # 检查是否已存在
            existing = (
                session.query(ScraperFollow)
                .filter_by(username=username)
                .first()
            )

            if existing:
                print(f"  [跳过] {username} - 已存在")
                skipped_count += 1
                continue

            try:
                follow = ScraperFollow(
                    username=username,
                    reason=reason,
                    added_by="admin",
                    is_active=True,
                )
                session.add(follow)
                session.flush()  # 立即检测约束冲突
                print(f"  [导入] {username} - {reason}")
                success_count += 1
            except Exception as e:
                session.rollback()
                print(f"  [失败] {username} - {e}")
                failed_count += 1

        session.commit()

        # 汇总
        print("=" * 60)
        print("导入完成！")
        print(f"  成功: {success_count}")
        print(f"  跳过: {skipped_count}")
        print(f"  失败: {failed_count}")
        print("=" * 60)

        # 验证：查询所有活跃账号
        total = (
            session.query(ScraperFollow)
            .filter_by(is_active=True)
            .count()
        )
        print(f"\n当前 scraper_follows 表活跃账号总数: {total}")

        # 列出所有账号
        print("\n所有活跃账号列表:")
        follows = (
            session.query(ScraperFollow)
            .filter_by(is_active=True)
            .order_by(ScraperFollow.id)
            .all()
        )
        for i, f in enumerate(follows, 1):
            print(f"  {i:>3}. {f.username:<20} | {f.reason}")


if __name__ == "__main__":
    seed_follows()
