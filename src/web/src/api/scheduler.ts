/** 抓取管理 API 客户端。 */

import { client } from "./client"
import type {
  ScheduleConfig,
  UpdateIntervalRequest,
  UpdateNextRunRequest,
  FetchAnalysisResponse,
  FollowStats,
  TweetTimeRange,
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

  /** 获取所有活跃账号的运行时统计 */
  async getFollowsStats(): Promise<FollowStats[]> {
    const response = await client.get<FollowStats[]>(
      "/admin/scraping/follows/stats",
    )
    return response.data
  },

  /** 获取所有活跃账号的推文时间范围 */
  async getTweetTimeRange(): Promise<TweetTimeRange[]> {
    const response = await client.get<TweetTimeRange[]>(
      "/admin/scraping/follows/tweet-time-range",
    )
    return response.data
  },

  /** 获取账号抓取分析 */
  async getFollowAnalysis(
    username: string,
    intervalHours: number = 12,
  ): Promise<FetchAnalysisResponse> {
    const response = await client.get<FetchAnalysisResponse>(
      `/admin/scraping/follows/${username}/analysis`,
      { params: { interval_hours: intervalHours } },
    )
    return response.data
  },
}
