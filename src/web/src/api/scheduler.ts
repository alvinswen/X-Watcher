/** 调度管理 API 客户端。 */

import { client } from "./client"
import type {
  ScheduleConfig,
  UpdateIntervalRequest,
  UpdateNextRunRequest,
} from "@/types"

/** 调度管理 API 路径前缀 */
const SCHEDULER_PREFIX = "/admin/scraping/schedule"

/** 调度管理 API 客户端 */
export const schedulerApi = {
  /** 获取调度配置 */
  async getConfig(): Promise<ScheduleConfig> {
    const response = await client.get<ScheduleConfig>(SCHEDULER_PREFIX)
    return response.data
  },

  /** 更新抓取间隔 */
  async updateInterval(data: UpdateIntervalRequest): Promise<ScheduleConfig> {
    const response = await client.put<ScheduleConfig>(
      `${SCHEDULER_PREFIX}/interval`,
      data,
    )
    return response.data
  },

  /** 更新下次执行时间 */
  async updateNextRun(data: UpdateNextRunRequest): Promise<ScheduleConfig> {
    const response = await client.put<ScheduleConfig>(
      `${SCHEDULER_PREFIX}/next-run`,
      data,
    )
    return response.data
  },

  /** 启用调度 */
  async enable(): Promise<ScheduleConfig> {
    const response = await client.post<ScheduleConfig>(
      `${SCHEDULER_PREFIX}/enable`,
    )
    return response.data
  },

  /** 禁用调度 */
  async disable(): Promise<ScheduleConfig> {
    const response = await client.post<ScheduleConfig>(
      `${SCHEDULER_PREFIX}/disable`,
    )
    return response.data
  },
}
