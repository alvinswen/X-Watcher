"""测试优化后的 RT/QT 摘要 prompt 效果。

从数据库查询有 referenced_tweet_author_username 的推文，
生成 prompt 并调用 LLM，打印摘要和翻译结果。
"""

import asyncio
import io
import os
import sqlite3
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# 加载 .env
from dotenv import load_dotenv
load_dotenv()

from src.summarization.domain.models import PromptConfig, TweetType


def get_test_tweets():
    """从数据库查询有 referenced_tweet_author_username 的推文。"""
    conn = sqlite3.connect("news_agent.db")
    c = conn.cursor()
    c.execute("""
        SELECT tweet_id, author_username, reference_type, text,
               referenced_tweet_text, referenced_tweet_author_username
        FROM tweets
        WHERE referenced_tweet_author_username IS NOT NULL
        ORDER BY db_created_at DESC
    """)
    rows = c.fetchall()
    conn.close()
    return rows


def determine_tweet_type(reference_type: str | None) -> TweetType:
    if reference_type == "retweeted":
        return TweetType.retweeted
    elif reference_type == "quoted":
        return TweetType.quoted
    elif reference_type == "replied_to":
        return TweetType.replied_to
    return TweetType.original


async def call_llm(prompt: str) -> str:
    """调用 OpenRouter API。"""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=os.getenv("OPENROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1",
        timeout=30,
    )
    response = await client.chat.completions.create(
        model="anthropic/claude-sonnet-4.5",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=500,
        temperature=0.7,
    )
    return response.choices[0].message.content or ""


async def main():
    tweets = get_test_tweets()
    if not tweets:
        print("没有找到有 referenced_tweet_author_username 的推文")
        return

    config = PromptConfig()

    for i, (tweet_id, author, ref_type, text, ref_text, ref_author) in enumerate(tweets):
        tweet_type = determine_tweet_type(ref_type)

        # 组装输入文本（和 service 逻辑一致）
        input_text = text
        if ref_text:
            if tweet_type == TweetType.retweeted:
                input_text = ref_text
            elif tweet_type == TweetType.quoted:
                input_text = f"{text}\n\n[引用原文]: {ref_text}"

        is_short = len(input_text) < config.min_tweet_length_for_summary

        # 生成 prompt
        prompt = config.format_unified_prompt(
            tweet_text=input_text,
            tweet_type=tweet_type,
            is_short=is_short,
            author_username=author,
            original_author=ref_author,
        )

        print(f"\n{'='*60}")
        print(f"[{i+1}/{len(tweets)}] @{author} {ref_type} @{ref_author}")
        print(f"原文: {text[:100]}{'...' if len(text) > 100 else ''}")
        if ref_text:
            print(f"引用原文: {ref_text[:100]}{'...' if len(ref_text) > 100 else ''}")
        print(f"is_short: {is_short}")
        print(f"\n--- 生成的 Prompt ---")
        print(prompt[:500])
        if len(prompt) > 500:
            print(f"... (总长 {len(prompt)} 字符)")

        print(f"\n--- LLM 响应 ---")
        try:
            response = await call_llm(prompt)
            print(response)
        except Exception as e:
            print(f"LLM 调用失败: {e}")

        print()


if __name__ == "__main__":
    asyncio.run(main())
