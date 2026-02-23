/** 统计分析 API 客户端。 */

import { client } from "./client"
import type { PostingFrequencyResponse } from "@/types/analytics"

const PREFIX = "/analytics"

export const analyticsApi = {
  /** 获取主题发文频次分布 */
  async getPostingFrequency(
    topicId: number,
    params?: { tz_offset?: number; slots?: number },
  ): Promise<PostingFrequencyResponse> {
    const response = await client.get<PostingFrequencyResponse>(
      `${PREFIX}/topics/${topicId}/posting-frequency`,
      { params },
    )
    return response.data
  },
}
