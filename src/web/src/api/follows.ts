/** 抓取账号 API 客户端。 */

import { client } from "./client"
import type {
  ScrapingFollow,
  AddScrapingFollowRequest,
  UpdateScrapingFollowRequest,
  XUserProfile,
} from "@/types"

/** 抓取账号 API 路径前缀 */
const FOLLOWS_PREFIX = "/admin/scraping/follows"

/** 抓取账号 API 客户端 */
export const followsApi = {
  /** 获取所有抓取账号 */
  async list(): Promise<ScrapingFollow[]> {
    const response = await client.get<ScrapingFollow[]>(FOLLOWS_PREFIX)
    return response.data
  },

  /** 添加抓取账号 */
  async add(request: AddScrapingFollowRequest): Promise<ScrapingFollow> {
    const response = await client.post<ScrapingFollow>(
      FOLLOWS_PREFIX,
      request,
    )
    return response.data
  },

  /** 更新抓取账号 */
  async update(
    username: string,
    request: UpdateScrapingFollowRequest,
  ): Promise<ScrapingFollow> {
    const response = await client.put<ScrapingFollow>(
      `${FOLLOWS_PREFIX}/${username}`,
      request,
    )
    return response.data
  },

  /** 删除抓取账号 */
  async delete(username: string): Promise<void> {
    await client.delete(`${FOLLOWS_PREFIX}/${username}`)
  },

  /** 切换账号活跃状态 */
  async toggleActive(
    username: string,
    isActive: boolean,
  ): Promise<ScrapingFollow> {
    return this.update(username, { is_active: isActive })
  },

  /** 获取所有用户档案 */
  async listProfiles(): Promise<XUserProfile[]> {
    const response = await client.get<XUserProfile[]>(
      `${FOLLOWS_PREFIX}/profiles`,
    )
    return response.data
  },

  /** 获取单个用户档案 */
  async getProfile(username: string): Promise<XUserProfile> {
    const response = await client.get<XUserProfile>(
      `${FOLLOWS_PREFIX}/${username}/profile`,
    )
    return response.data
  },

  /** 手动同步用户档案 */
  async syncProfiles(): Promise<{ synced: number; message: string }> {
    const response = await client.post<{ synced: number; message: string }>(
      `${FOLLOWS_PREFIX}/sync-profiles`,
    )
    return response.data
  },

  /** 为单个账号生成极简介绍 */
  async generateIntro(username: string): Promise<ScrapingFollow> {
    const response = await client.post<ScrapingFollow>(
      `${FOLLOWS_PREFIX}/${username}/generate-intro`,
      undefined,
      { timeout: 120_000 },
    )
    return response.data
  },
}
