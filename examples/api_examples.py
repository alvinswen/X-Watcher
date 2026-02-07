"""SeriousNewsAgent API 使用示例。

本示例演示如何使用 SeriousNewsAgent 的各种 API 接口。
"""

import time
from typing import Any

import requests

# API 基础地址
BASE_URL = "http://localhost:8000"


class NewsAgentClient:
    """SeriousNewsAgent API 客户端。"""

    def __init__(self, base_url: str = BASE_URL):
        """初始化客户端。

        Args:
            base_url: API 基础地址
        """
        self.base_url = base_url.rstrip("/")

    def health_check(self) -> dict[str, Any]:
        """健康检查。

        Returns:
            dict: 健康状态
        """
        response = requests.get(f"{self.base_url}/health")
        response.raise_for_status()
        return response.json()

    # ==================== 抓取 API ====================

    def start_scraping(
        self,
        usernames: str | list[str],
        limit: int = 100,
    ) -> str:
        """启动抓取任务。

        Args:
            usernames: 用户名（逗号分隔的字符串或列表）
            limit: 每个用户抓取数量

        Returns:
            str: 任务 ID
        """
        if isinstance(usernames, list):
            usernames = ",".join(usernames)

        response = requests.post(
            f"{self.base_url}/api/admin/scrape",
            json={"usernames": usernames, "limit": limit},
        )
        response.raise_for_status()
        return response.json()["task_id"]

    def get_scraping_status(self, task_id: str) -> dict[str, Any]:
        """查询抓取任务状态。

        Args:
            task_id: 任务 ID

        Returns:
            dict: 任务状态信息
        """
        response = requests.get(f"{self.base_url}/api/admin/scrape/{task_id}")
        response.raise_for_status()
        return response.json()

    def list_scraping_tasks(self, status: str | None = None) -> list[dict[str, Any]]:
        """列出所有抓取任务。

        Args:
            status: 可选的状态过滤器

        Returns:
            list: 任务列表
        """
        params = {"status": status} if status else {}
        response = requests.get(f"{self.base_url}/api/admin/scrape", params=params)
        response.raise_for_status()
        return response.json()

    def delete_scraping_task(self, task_id: str) -> dict[str, Any]:
        """删除抓取任务。

        Args:
            task_id: 任务 ID

        Returns:
            dict: 删除结果
        """
        response = requests.delete(f"{self.base_url}/api/admin/scrape/{task_id}")
        response.raise_for_status()
        return response.json()

    # ==================== 去重 API ====================

    def start_deduplication(
        self,
        tweet_ids: list[str],
        config: dict[str, Any] | None = None,
    ) -> str:
        """启动去重任务。

        Args:
            tweet_ids: 推文 ID 列表
            config: 可选的去重配置

        Returns:
            str: 任务 ID
        """
        payload = {"tweet_ids": tweet_ids}
        if config:
            payload["config"] = config

        response = requests.post(
            f"{self.base_url}/api/deduplicate/batch",
            json=payload,
        )
        response.raise_for_status()
        return response.json()["task_id"]

    def get_deduplication_group(self, group_id: str) -> dict[str, Any]:
        """查询去重组详情。

        Args:
            group_id: 去重组 ID

        Returns:
            dict: 去重组信息
        """
        response = requests.get(f"{self.base_url}/api/deduplicate/groups/{group_id}")
        response.raise_for_status()
        return response.json()

    def get_tweet_deduplication(self, tweet_id: str) -> dict[str, Any]:
        """查询推文的去重状态。

        Args:
            tweet_id: 推文 ID

        Returns:
            dict: 去重信息
        """
        response = requests.get(f"{self.base_url}/api/deduplicate/tweets/{tweet_id}")
        response.raise_for_status()
        return response.json()

    def delete_deduplication_group(self, group_id: str) -> dict[str, Any]:
        """撤销去重。

        Args:
            group_id: 去重组 ID

        Returns:
            dict: 删除结果
        """
        response = requests.delete(f"{self.base_url}/api/deduplicate/groups/{group_id}")
        response.raise_for_status()
        return response.json()

    # ==================== 摘要 API ====================

    def start_summarization(
        self,
        tweet_ids: list[str],
        force_refresh: bool = False,
    ) -> str:
        """启动摘要任务。

        Args:
            tweet_ids: 推文 ID 列表
            force_refresh: 是否强制刷新缓存

        Returns:
            str: 任务 ID
        """
        response = requests.post(
            f"{self.base_url}/api/summaries/batch",
            json={"tweet_ids": tweet_ids, "force_refresh": force_refresh},
        )
        response.raise_for_status()
        return response.json()["task_id"]

    def get_tweet_summary(self, tweet_id: str) -> dict[str, Any]:
        """获取推文摘要。

        Args:
            tweet_id: 推文 ID

        Returns:
            dict: 摘要信息
        """
        response = requests.get(f"{self.base_url}/api/summaries/tweets/{tweet_id}")
        response.raise_for_status()
        return response.json()

    def regenerate_summary(self, tweet_id: str) -> dict[str, Any]:
        """重新生成推文摘要。

        Args:
            tweet_id: 推文 ID

        Returns:
            dict: 新生成的摘要
        """
        response = requests.post(
            f"{self.base_url}/api/summaries/tweets/{tweet_id}/regenerate",
        )
        response.raise_for_status()
        return response.json()

    def get_cost_statistics(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """查询成本统计。

        Args:
            start_date: 开始日期（ISO 8601 格式）
            end_date: 结束日期（ISO 8601 格式）

        Returns:
            dict: 成本统计信息
        """
        params = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        response = requests.get(
            f"{self.base_url}/api/summaries/stats",
            params=params,
        )
        response.raise_for_status()
        return response.json()

    # ==================== 工具方法 ====================

    def wait_for_task(
        self,
        task_id: str,
        api_type: str = "scraping",
        timeout: int = 300,
        interval: int = 2,
    ) -> dict[str, Any]:
        """等待任务完成。

        Args:
            task_id: 任务 ID
            api_type: API 类型（scraping、deduplication、summaries）
            timeout: 超时时间（秒）
            interval: 轮询间隔（秒）

        Returns:
            dict: 任务结果
        """
        start_time = time.time()
        endpoint_map = {
            "scraping": f"{self.base_url}/api/admin/scrape/{task_id}",
            "deduplication": f"{self.base_url}/api/deduplicate/tasks/{task_id}",
            "summaries": f"{self.base_url}/api/summaries/tasks/{task_id}",
        }

        url = endpoint_map.get(api_type, endpoint_map["scraping"])

        while True:
            if time.time() - start_time > timeout:
                raise TimeoutError(f"任务 {task_id} 超时")

            response = requests.get(url)
            response.raise_for_status()
            data = response.json()

            if data["status"] in ["completed", "failed"]:
                return data

            print(f"任务状态: {data['status']}, 进度: {data.get('progress', {}).get('percentage', 0)}%")
            time.sleep(interval)


# ==================== 使用示例 ====================

def example_health_check():
    """示例：健康检查。"""
    print("=== 健康检查 ===")
    client = NewsAgentClient()
    result = client.health_check()
    print(f"服务状态: {result['status']}\n")


def example_scraping():
    """示例：抓取推文。"""
    print("=== 抓取推文 ===")
    client = NewsAgentClient()

    # 启动抓取任务
    print("启动抓取任务...")
    task_id = client.start_scraping(usernames=["OpenAI", "nvidia"], limit=5)
    print(f"任务 ID: {task_id}")

    # 等待任务完成
    print("等待任务完成...")
    result = client.wait_for_task(task_id, api_type="scraping")

    if result["status"] == "completed":
        print(f"抓取成功! 结果: {result.get('result', {})}")
    else:
        print(f"抓取失败: {result.get('error', 'Unknown error')}")

    # 列出所有任务
    print("\n所有任务:")
    tasks = client.list_scraping_tasks()
    for task in tasks[:3]:  # 只显示前 3 个
        print(f"  - {task['task_id']}: {task['status']}")


def example_deduplication():
    """示例：推文去重。"""
    print("=== 推文去重 ===")
    client = NewsAgentClient()

    # 假设我们有这些推文 ID
    tweet_ids = ["1234567890", "0987654321", "1122334455"]

    # 启动去重任务
    print("启动去重任务...")
    task_id = client.start_deduplication(tweet_ids)
    print(f"任务 ID: {task_id}")

    # 等待任务完成
    result = client.wait_for_task(task_id, api_type="deduplication")

    if result["status"] == "completed":
        print(f"去重完成! 处理了 {result['result'].get('total_tweets', 0)} 条推文")


def example_summarization():
    """示例：生成摘要。"""
    print("=== 生成摘要 ===")
    client = NewsAgentClient()

    # 假设我们有这些推文 ID
    tweet_ids = ["1234567890", "0987654321"]

    # 启动摘要任务
    print("启动摘要任务...")
    task_id = client.start_summarization(tweet_ids)
    print(f"任务 ID: {task_id}")

    # 等待任务完成
    result = client.wait_for_task(task_id, api_type="summaries")

    if result["status"] == "completed":
        print(f"摘要完成!")
        print(f"  处理推文: {result['result'].get('total_tweets', 0)} 条")
        print(f"  Token 使用: {result['result'].get('total_tokens', 0)}")
        print(f"  成本: ${result['result'].get('total_cost_usd', 0):.4f}")

        # 获取单条推文摘要
        summary = client.get_tweet_summary(tweet_ids[0])
        print(f"\n推文摘要: {summary.get('summary_chinese', 'N/A')}")

    # 查询成本统计
    stats = client.get_cost_statistics()
    print(f"\n成本统计:")
    print(f"  总成本: ${stats['total_cost_usd']:.4f}")
    print(f"  总 Token: {stats['total_tokens']}")


def example_complete_workflow():
    """示例：完整工作流。"""
    print("=== 完整工作流 ===")
    client = NewsAgentClient()

    # 1. 检查服务健康状态
    health = client.health_check()
    print(f"1. 服务状态: {health['status']}")

    # 2. 抓取推文
    print("\n2. 抓取推文...")
    task_id = client.start_scraping(usernames=["OpenAI"], limit=10)
    result = client.wait_for_task(task_id, api_type="scraping")
    print(f"   抓取完成: {result['status']}")

    if result["status"] == "completed" and result.get("result"):
        # 假设返回了推文 ID
        # 这里使用模拟 ID 进行演示
        tweet_ids = ["1234567890"]

        # 3. 去重
        print("\n3. 去重...")
        dedup_task_id = client.start_deduplication(tweet_ids)
        client.wait_for_task(dedup_task_id, api_type="deduplication")

        # 4. 生成摘要
        print("\n4. 生成摘要...")
        summary_task_id = client.start_summarization(tweet_ids)
        client.wait_for_task(summary_task_id, api_type="summaries")

        # 5. 获取摘要结果
        summary = client.get_tweet_summary(tweet_ids[0])
        print(f"\n5. 摘要结果:")
        print(f"   {summary.get('summary_chinese', 'N/A')}")


if __name__ == "__main__":
    # 运行示例
    try:
        example_health_check()
        # 取消注释以下行来运行其他示例
        # example_scraping()
        # example_deduplication()
        # example_summarization()
        # example_complete_workflow()

    except requests.exceptions.ConnectionError:
        print("错误: 无法连接到服务器。请确保服务正在运行 (python -m src.main)")
    except Exception as e:
        print(f"错误: {e}")
