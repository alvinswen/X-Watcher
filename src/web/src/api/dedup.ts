/** 去重 API 客户端。 */

import { client } from "./client"
import type { TaskStatusResponse } from "@/types"

/** 去重 API 路径前缀 */
const DEDUP_PREFIX = "/deduplicate"

/** 去重 API 客户端 */
export const dedupApi = {
  /** 批量去重 */
  async batchDeduplicate(tweetIds: string[]): Promise<{ task_id: string; status: string }> {
    const response = await client.post<{ task_id: string; status: string }>(
      `${DEDUP_PREFIX}/batch`,
      { tweet_ids: tweetIds },
    )
    return response.data
  },

  /** 查询去重任务状态 */
  async getTaskStatus(taskId: string): Promise<TaskStatusResponse> {
    const response = await client.get<TaskStatusResponse>(
      `${DEDUP_PREFIX}/tasks/${taskId}`,
    )
    return response.data
  },
}
