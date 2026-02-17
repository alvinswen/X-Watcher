/** 调度相关类型定义。 */

/** 调度器配置响应。 */
export interface ScheduleConfig {
  /** 抓取间隔（秒） */
  interval_seconds: number
  /** 下次执行时间（ISO 8601） */
  next_run_time: string | null
  /** 调度器是否正在运行 */
  scheduler_running: boolean
  /** 抓取任务是否激活 */
  job_active: boolean
  /** 调度是否启用 */
  is_enabled: boolean
  /** 最后更新时间 */
  updated_at: string | null
  /** 最后更新人 */
  updated_by: string | null
  /** 附加信息 */
  message: string | null
}

/** 更新间隔请求。 */
export interface UpdateIntervalRequest {
  /** 抓取间隔（秒），300-604800 */
  interval_seconds: number
}

/** 更新下次执行时间请求。 */
export interface UpdateNextRunRequest {
  /** 下次执行时间（ISO 8601，必须为未来） */
  next_run_time: string
}

/** 单个周期统计。 */
export interface PeriodStats {
  /** 周期开始时间 */
  period_start: string
  /** 周期结束时间 */
  period_end: string
  /** 新推文数量 */
  new_tweet_count: number
}

/** 账号运行时统计。 */
export interface FollowStats {
  /** 用户名 */
  username: string
  /** 自动计算模式下的当前 limit 值 */
  effective_limit: number
  /** 近 14 个 12h 周期的最大新推文数 */
  max_count_12h: number
  /** 近 14 个 24h 周期的最大新推文数 */
  max_count_24h: number
}

/** 抓取分析响应。 */
export interface FetchAnalysisResponse {
  /** 用户名 */
  username: string
  /** 周期间隔小时数 */
  interval_hours: number
  /** 各周期统计 */
  periods: PeriodStats[]
  /** 总新推文数 */
  total_new_tweets: number
}
