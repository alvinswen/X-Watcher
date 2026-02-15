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

  /** 补缺预览：查询缺少摘要的推文数量 */
  async previewBackfill(params?: { since?: string; until?: string }): Promise<{ tweet_count: number }> {
    const response = await client.get<{ tweet_count: number }>(
      `${SUMMARIES_PREFIX}/backfill/preview`,
      { params },
    )
    return response.data
  },

  /** 执行补缺：为缺少摘要的推文批量生成摘要 */
  async startBackfill(params?: { since?: string; until?: string }): Promise<{ task_id: string; status: string; tweet_count: number }> {
    const response = await client.post<{ task_id: string; status: string; tweet_count: number }>(
      `${SUMMARIES_PREFIX}/backfill`,
      params,
    )
    return response.data
  },

  /** 重置预览：查询时间范围内的推文数量 */
  async previewReset(params: { since: string; until: string }): Promise<{ tweet_count: number }> {
    const response = await client.get<{ tweet_count: number }>(
      `${SUMMARIES_PREFIX}/reset/preview`,
      { params },
    )
    return response.data
  },

  /** 执行重置：对时间范围内所有推文重新生成摘要 */
  async startReset(params: { since: string; until: string }): Promise<{ task_id: string; status: string; tweet_count: number }> {
    const response = await client.post<{ task_id: string; status: string; tweet_count: number }>(
      `${SUMMARIES_PREFIX}/reset`,
      params,
    )
    return response.data
  },
}
