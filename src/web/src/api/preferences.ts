/** 用户偏好 API 客户端（用户自助操作）。 */

import { client } from "./client"
import type { UserFollow, BatchFollowResponse } from "@/types"

/** 偏好 API 路径前缀 */
const PREFS_PREFIX = "/preferences"

/** 用户偏好 API 客户端 */
export const preferencesApi = {
  /** 获取当前用户关注列表 */
  async getFollows(): Promise<UserFollow[]> {
    const response = await client.get<UserFollow[]>(
      `${PREFS_PREFIX}/follows`,
    )
    return response.data
  },

  /** 添加关注 */
  async addFollow(username: string): Promise<UserFollow> {
    const response = await client.post<UserFollow>(
      `${PREFS_PREFIX}/follows`,
      { username },
    )
    return response.data
  },

  /** 移除关注 */
  async removeFollow(username: string): Promise<void> {
    await client.delete(`${PREFS_PREFIX}/follows/${username}`)
  },

  /** 批量添加关注 */
  async batchAddFollows(usernames: string[]): Promise<BatchFollowResponse> {
    const response = await client.post<BatchFollowResponse>(
      `${PREFS_PREFIX}/follows/batch`,
      { usernames },
    )
    return response.data
  },

  /** 批量移除关注 */
  async batchRemoveFollows(usernames: string[]): Promise<BatchFollowResponse> {
    const response = await client.delete<BatchFollowResponse>(
      `${PREFS_PREFIX}/follows/batch`,
      { data: { usernames } },
    )
    return response.data
  },
}
