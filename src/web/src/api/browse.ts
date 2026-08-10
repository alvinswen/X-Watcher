/** 推文浏览 API 客户端。 */

import { client } from "./client"
import type {
  AuthorListResponse,
  AuthorTimelineParams,
  AuthorTimelineResponse,
  BrowseTweetListParams,
  BrowseTweetListResponse,
  DailyStatsResponse,
} from "@/types"

/** 浏览 API 路径前缀 */
const BROWSE_PREFIX = "/browse"

/** 获取浏览器时区偏移量（分钟），传给后端用于本地时区日期分组 */
function getTzOffset(): number {
  return new Date().getTimezoneOffset()
}

/** 推文浏览 API 客户端 */
export const browseApi = {
  /** 获取每日推文统计 */
  async getDailyStats(
    year: number,
    month: number,
    min_text_length?: number,
    reading_layer?: boolean,
  ): Promise<DailyStatsResponse> {
    const response = await client.get<DailyStatsResponse>(
      `${BROWSE_PREFIX}/stats/daily`,
      { params: { year, month, tz_offset: getTzOffset(), min_text_length, reading_layer } },
    )
    return response.data
  },

  /** 获取作者列表 */
  async getAuthors(params: {
    date: string
    min_text_length?: number
    reading_layer?: boolean
  }): Promise<AuthorListResponse> {
    const response = await client.get<AuthorListResponse>(
      `${BROWSE_PREFIX}/authors`,
      { params: { ...params, tz_offset: getTzOffset() } },
    )
    return response.data
  },

  /** 获取推文浏览列表 */
  async getTweets(
    params: BrowseTweetListParams,
  ): Promise<BrowseTweetListResponse> {
    const response = await client.get<BrowseTweetListResponse>(
      `${BROWSE_PREFIX}/tweets`,
      { params: { ...params, tz_offset: getTzOffset() } },
    )
    return response.data
  },

  /** 获取作者时间线 */
  async getAuthorTimeline(
    params: AuthorTimelineParams,
  ): Promise<AuthorTimelineResponse> {
    const response = await client.get<AuthorTimelineResponse>(
      `${BROWSE_PREFIX}/author-timeline`,
      { params: { ...params, tz_offset: getTzOffset() } },
    )
    return response.data
  },
}
