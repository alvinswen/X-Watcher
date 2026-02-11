/** 抓取账号 API 客户端。 */

import { client } from "./client"
import type {
  ScrapingFollow,
  AddScrapingFollowRequest,
  UpdateScrapingFollowRequest,
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
}
