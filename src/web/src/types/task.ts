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
  /** 任务状态 */
  status: TaskStatus
  /** 创建时间 */
  created_at: string | null
  /** 进度信息 */
  progress: TaskProgress
  /** 错误信息 */
  error: string | null
  /** 结果信息 */
  result: Record<string, unknown> | null
}

/** 抓取账号信息。 */
export interface ScrapingFollow {
  /** ID */
  id: number
  /** 用户名 */
  username: string
  /** 添加时间 */
  added_at: string
  /** 添加理由 */
  reason: string
  /** 添加人 */
  added_by: string
  /** 是否活跃 */
  is_active: boolean
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

/** 更新抓取账号请求。 */
export interface UpdateScrapingFollowRequest {
  /** 用户名 */
  username?: string
  /** 添加理由 */
  reason?: string
  /** 是否活跃 */
  is_active?: boolean
}
