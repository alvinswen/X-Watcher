/** 推文浏览 API 客户端。 */

import { client } from "./client"
import type {
  AuthorListResponse,
  BrowseTweetListParams,
  BrowseTweetListResponse,
  DailyStatsResponse,
} from "@/types"

/** 浏览 API 路径前缀 */
const BROWSE_PREFIX = "/browse"

/** 推文浏览 API 客户端 */
export const browseApi = {
  /** 获取每日推文统计 */
  async getDailyStats(
    year: number,
    month: number,
  ): Promise<DailyStatsResponse> {
    const response = await client.get<DailyStatsResponse>(
      `${BROWSE_PREFIX}/stats/daily`,
      { params: { year, month } },
    )
    return response.data
  },

  /** 获取作者列表 */
  async getAuthors(params: {
    date: string
  }): Promise<AuthorListResponse> {
    const response = await client.get<AuthorListResponse>(
      `${BROWSE_PREFIX}/authors`,
      { params },
    )
    return response.data
  },

  /** 获取推文浏览列表 */
  async getTweets(
    params: BrowseTweetListParams,
  ): Promise<BrowseTweetListResponse> {
    const response = await client.get<BrowseTweetListResponse>(
      `${BROWSE_PREFIX}/tweets`,
      { params },
    )
    return response.data
  },
}
