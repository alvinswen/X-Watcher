/** 系统状态 API 客户端。 */

import { client } from "./client"
import type {
  StatusOverviewResponse,
  ConfigValidateResponse,
  TwitterBalanceResponse,
} from "@/types/status"

/** 系统状态 API */
export const statusApi = {
  /** 获取系统状态概览 */
  async getOverview(): Promise<StatusOverviewResponse> {
    const response = await client.get<StatusOverviewResponse>("/status/overview")
    return response.data
  },

  /** 获取 TwitterAPI.io 账户余额（默认走后端 10 分钟缓存，force=true 强制刷新） */
  async getTwitterBalance(force = false): Promise<TwitterBalanceResponse> {
    const response = await client.get<TwitterBalanceResponse>("/status/twitter-balance", {
      params: { force },
    })
    return response.data
  },
}

/** 配置验证 API */
export const configApi = {
  /** 验证服务连通性 */
  async validate(): Promise<ConfigValidateResponse> {
    const response = await client.get<ConfigValidateResponse>("/admin/config/validate")
    return response.data
  },
}
