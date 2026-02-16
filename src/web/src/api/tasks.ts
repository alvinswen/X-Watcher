/** 任务 API 客户端。 */

import { client } from "./client"
import type {
  ScrapeTriggerRequest,
  ScrapeTriggerResponse,
  TaskStatusResponse,
  TaskListItem,
  TaskHistoryItem,
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

  /** 查询任务状态 */
  async getStatus(taskId: string): Promise<TaskStatusResponse> {
    const response = await client.get<TaskStatusResponse>(
      `${TASKS_PREFIX}/${taskId}`,
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

  /** 删除任务 */
  async deleteTask(taskId: string): Promise<{ message: string }> {
    const response = await client.delete<{ message: string }>(
      `${TASKS_PREFIX}/${taskId}`,
    )
    return response.data
  },

  /** 查询持久化的任务执行历史（重启后仍保留） */
  async getHistory(limit = 50, status?: string): Promise<TaskHistoryItem[]> {
    const params: Record<string, string | number> = { limit }
    if (status) params.status = status
    const response = await client.get<TaskHistoryItem[]>("/admin/tasks/history", {
      params,
    })
    return response.data
  },
}
