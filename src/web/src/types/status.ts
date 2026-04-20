/** 系统状态概览相关类型定义。 */

/** 推文统计 */
export interface TweetsStatus {
  total: number
  latest_tweet_at: string | null
  today_count: number
}

/** 关注统计 */
export interface FollowsStatus {
  total: number
  active: number
  inactive: number
}

/** 摘要统计 */
export interface SummariesStatus {
  total: number
  pending_tweets: number
}

/** 主题统计 */
export interface TopicsStatus {
  total: number
  latest_summary_at: string | null
  latest_summary_status: string | null
}

/** 调度器状态 */
export interface SchedulerStatus {
  status: string
  next_run_time: string | null
  interval_seconds: number
}

/** 系统信息 */
export interface SystemStatus {
  server_start_time: string | null
  database_size_mb: number | null
}

/** 状态概览响应 */
export interface StatusOverviewResponse {
  tweets: TweetsStatus
  follows: FollowsStatus
  summaries: SummariesStatus
  topics: TopicsStatus
  scheduler: SchedulerStatus
  system: SystemStatus
}

/** LLM 提供商验证结果 */
export interface LLMProviderValidation {
  name: string
  status: "healthy" | "unhealthy"
  model?: string
  latency_ms?: number
  error?: string
}

/** 服务连通性验证项 */
export interface ServiceValidation {
  status: "healthy" | "unhealthy"
  latency_ms?: number
  error?: string
}

/** 配置验证响应 */
export interface ConfigValidateResponse {
  llm_providers: LLMProviderValidation[]
  twitter_api: ServiceValidation
  database: ServiceValidation
}

/** TwitterAPI.io 余额响应 */
export interface TwitterBalanceResponse {
  recharge_credits: number | null
  fetched_at: string | null
  source: "live" | "cache" | "stale" | "error"
  error: string | null
  warning_threshold: number
  danger_threshold: number
}
