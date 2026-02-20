/** 搜索 API 客户端。 */

import { client } from "./client"
import type { SearchParams, SearchResponse } from "@/types/search"

/** 搜索 API 路径前缀 */
const SEARCH_PREFIX = "/search"

/** 搜索 API 客户端 */
export const searchApi = {
  /** 搜索推文 */
  async searchTweets(params: SearchParams): Promise<SearchResponse> {
    const response = await client.get<SearchResponse>(
      `${SEARCH_PREFIX}/tweets`,
      { params },
    )
    return response.data
  },
}
