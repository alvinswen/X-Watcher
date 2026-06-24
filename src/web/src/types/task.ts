/** 任务相关类型定义。 */

/** 任务状态类型 */
export type TaskStatus = "pending" | "running" | "completed" | "failed"

/** 任务进度信息。 */
export interface TaskProgress {
  /** 当前数量 */
  current: number
  /** 总数量 */
  total: number
  /** 百分比 */
  percentage: number
}

/** 任务状态响应。 */
export interface TaskStatusResponse {
  /** 任务 ID */
  task_id: string
  /** 任务状态 */
  status: TaskStatus
  /** 任务结果（完成时） */
  result: Record<string, unknown> | null
  /** 错误信息（失败时） */
  error: string | null
  /** 创建时间 */
  created_at: string | null
  /** 开始时间 */
  started_at: string | null
  /** 完成时间 */
  completed_at: string | null
  /** 进度信息 */
  progress: TaskProgress
  /** 元数据 */
  metadata: Record<string, unknown>
}

/** 触发抓取请求。 */
export interface ScrapeTriggerRequest {
  /** 用户名列表（逗号分隔） */
  usernames: string
  /** 抓取数量限制 */
  limit?: number
}

/** 触发抓取响应。 */
export interface ScrapeTriggerResponse {
  /** 任务 ID */
  task_id: string
  /** 任务状态 */
  status: string
}

/** 任务列表项（简化版）。 */
export interface TaskListItem {
  /** 任务 ID */
  task_id: string
  /** 任务名称 */
  task_name: string
  /** 任务状态 */
  status: TaskStatus
  /** 创建时间 */
  created_at: string | null
  /** 开始时间 */
  started_at: string | null
  /** 进度信息 */
  progress: TaskProgress
  /** 错误信息 */
  error: string | null
  /** 结果信息 */
  result: Record<string, unknown> | null
  /** 元数据 */
  metadata: Record<string, unknown>
}

/** 抓取账号信息。 */
export interface ScrapingFollow {
  /** ID */
  id: number
  /** 用户名 */
  username: string
  /** X 平台永久 user_id（系统自动获取） */
  platform_user_id: string | null
  /** 添加时间 */
  added_at: string
  /** 添加理由 */
  reason: string
  /** 添加人 */
  added_by: string
  /** 是否活跃 */
  is_active: boolean
  /** 手动推文数量限制（null 表示自动计算） */
  manual_limit: number | null
  /** 极简介绍（≤10汉字） */
  brief_intro: string | null
}

/** 添加抓取账号请求。 */
export interface AddScrapingFollowRequest {
  /** 用户名 */
  username: string
  /** 添加理由 */
  reason: string
  /** 添加人标识 */
  added_by: string
}

/** X 平台用户档案信息。 */
export interface XUserProfile {
  /** X 平台永久 user_id */
  platform_user_id: string
  /** 当前用户名 */
  username: string
  /** 显示名称 */
  display_name: string | null
  /** 蓝标认证 */
  is_blue_verified: boolean
  /** 认证类型 */
  verified_type: string | null
  /** 头像 URL */
  profile_picture: string | null
  /** 封面图 URL */
  cover_picture: string | null
  /** 个人简介 */
  description: string | null
  /** 位置 */
  location: string | null
  /** 粉丝数 */
  followers_count: number | null
  /** 关注数 */
  following_count: number | null
  /** 推文总数 */
  statuses_count: number | null
  /** 点赞数 */
  favourites_count: number | null
  /** 媒体推文数 */
  media_count: number | null
  /** 账号创建日期 */
  account_created_at: string | null
  /** 是否自动化账号 */
  is_automated: boolean
  /** 可能敏感 */
  possibly_sensitive: boolean
  /** 置顶推文 ID */
  pinned_tweet_ids: string[] | null
  /** 账号不可用 */
  unavailable: boolean
  /** 不可用原因 */
  unavailable_reason: string | null
  /** 数据获取时间 */
  fetched_at: string
}

/** 更新抓取账号请求。 */
export interface UpdateScrapingFollowRequest {
  /** 用户名 */
  username?: string
  /** 添加理由 */
  reason?: string
  /** 是否活跃 */
  is_active?: boolean
  /** 手动推文数量限制（0 清除，null 不修改） */
  manual_limit?: number | null
  /** 极简介绍（≤10汉字，null 不修改，空字符串清空） */
  brief_intro?: string | null
}
