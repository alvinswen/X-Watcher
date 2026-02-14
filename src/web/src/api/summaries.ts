/** 摘要 API 客户端。 */

import { client } from "./client"
import type { CostStats, TaskStatusResponse } from "@/types"

/** 摘要 API 路径前缀 */
const SUMMARIES_PREFIX = "/summaries"

/** 摘要 API 客户端 */
export const summariesApi = {
  /** 获取摘要成本统计 */
  async getStats(params?: { start_date?: string; end_date?: string }): Promise<CostStats> {
    const response = await client.get<CostStats>(
      `${SUMMARIES_PREFIX}/stats`,
      { params },
    )
    return response.data
  },

  /** 批量生成摘要 */
  async batchSummarize(tweetIds: string[], forceRefresh?: boolean): Promise<{ task_id: string; status: string }> {
    const response = await client.post<{ task_id: string; status: string }>(
      `${SUMMARIES_PREFIX}/batch`,
      { tweet_ids: tweetIds, force_refresh: forceRefresh },
    )
    return response.data
  },

  /** 重新生成单条推文摘要 */
  async regenerate(tweetId: string): Promise<Record<string, unknown>> {
    const response = await client.post<Record<string, unknown>>(
      `${SUMMARIES_PREFIX}/tweets/${tweetId}/regenerate`,
    )
    return response.data
  },

  /** 查询摘要任务状态 */
  async getTaskStatus(taskId: string): Promise<TaskStatusResponse> {
    const response = await client.get<TaskStatusResponse>(
      `${SUMMARIES_PREFIX}/tasks/${taskId}`,
    )
    return response.data
  },
}
