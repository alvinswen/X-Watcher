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
