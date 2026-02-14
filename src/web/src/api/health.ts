/** 健康检查 API 客户端。 */

import axios from "axios"
import type { HealthResponse } from "@/types"

/** 健康检查 API 客户端（IC-1：使用独立 axios，不经过 client.ts） */
export const healthApi = {
  /** 获取系统健康状态 */
  async getStatus(): Promise<HealthResponse> {
    const response = await axios.get<HealthResponse>("/health")
    return response.data
  },
}
