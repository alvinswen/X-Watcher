/** 推文 API 客户端。 */

import { client } from "./client"
import type {
  TweetDetail,
  TweetListParams,
  TweetListResponse,
} from "@/types"

/** 推文 API 路径前缀 */
const TWEETS_PREFIX = "/tweets"

/** 推文 API 客户端 */
export const tweetsApi = {
  /** 获取推文列表 */
  async getList(params?: TweetListParams): Promise<TweetListResponse> {
    const response = await client.get<TweetListResponse>(TWEETS_PREFIX, {
      params,
    })
    return response.data
  },

  /** 获取推文详情 */
  async getDetail(tweetId: string): Promise<TweetDetail> {
    const response = await client.get<TweetDetail>(
      `${TWEETS_PREFIX}/${tweetId}`,
    )
    return response.data
  },
}
