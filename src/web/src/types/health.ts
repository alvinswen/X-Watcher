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
