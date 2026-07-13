/** 任务 API 客户端。 */

import { client } from "./client"
import type {
  ScrapeTriggerRequest,
  ScrapeTriggerResponse,
  TaskListItem,
} from "@/types"

/** 任务 API 路径前缀 */
const TASKS_PREFIX = "/admin/scrape"

/** 任务 API 客户端 */
export const tasksApi = {
  /** 触发抓取任务 */
  async triggerScraping(request: ScrapeTriggerRequest): Promise<ScrapeTriggerResponse> {
    const response = await client.post<ScrapeTriggerResponse>(
      TASKS_PREFIX,
      request,
    )
    return response.data
  },

  /** 列出所有任务 */
  async listTasks(status?: string): Promise<TaskListItem[]> {
    const params = status ? { status } : undefined
    const response = await client.get<TaskListItem[]>(TASKS_PREFIX, {
      params,
    })
    return response.data
  },

}
