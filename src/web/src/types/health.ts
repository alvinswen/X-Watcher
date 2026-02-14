/** 健康检查相关类型定义。 */

/** 组件健康状态。 */
export interface ComponentHealth {
  /** 状态 */
  status: "healthy" | "unhealthy"
  /** 错误信息（unhealthy 时） */
  error?: string
  /** 其他属性（调度器特有） */
  [key: string]: unknown
}

/** 健康检查响应。 */
export interface HealthResponse {
  /** 整体状态 */
  status: "healthy" | "degraded"
  /** 各组件状态 */
  components: Record<string, ComponentHealth>
}

/** 摘要成本统计。 */
export interface CostStats {
  /** 起始日期 */
  start_date: string | null
  /** 结束日期 */
  end_date: string | null
  /** 总成本（USD） */
  total_cost_usd: number
  /** 总 token 数 */
  total_tokens: number
  /** 提示 token 数 */
  prompt_tokens: number
  /** 补全 token 数 */
  completion_tokens: number
  /** 各提供商统计 */
  provider_breakdown: Record<string, Record<string, number>>
}
