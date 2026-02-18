/** 主题管理类型定义。 */

/** 主题基本信息 */
export interface Topic {
  id: number
  name: string
  description: string | null
  created_at: string
  updated_at: string
}

/** 主题列表项（含账号数量） */
export interface TopicListItem {
  id: number
  name: string
  description: string | null
  account_count: number
  created_at: string
}

/** 主题账号 */
export interface TopicAccount {
  id: number
  username: string
  added_at: string
}

/** 主题详情（含账号列表） */
export interface TopicDetail extends Topic {
  accounts: TopicAccount[]
}

/** 创建主题请求 */
export interface CreateTopicRequest {
  name: string
  description?: string | null
}

/** 更新主题请求 */
export interface UpdateTopicRequest {
  name?: string | null
  description?: string | null
}

/** 批量设置账号请求 */
export interface SetAccountsRequest {
  usernames: string[]
}

/** 摘要任务状态 */
export type TopicSummaryTaskStatus = "pending" | "running" | "completed" | "failed"

/** 摘要结果 */
export interface TopicSummary {
  id: number
  content: string
  llm_provider: string
  llm_model: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  cost_usd: number
  tweet_count: number
  account_count: number
  created_at: string
}

/** 摘要任务列表项 */
export interface TopicSummaryTask {
  id: number
  topic_id: number | null
  topic_name: string | null
  time_span_hours: number
  deadline: string
  custom_prompt: string | null
  status: TopicSummaryTaskStatus
  error_message: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

/** 摘要任务详情（含摘要结果） */
export interface TopicSummaryTaskDetail extends TopicSummaryTask {
  summary: TopicSummary | null
}

/** 创建摘要任务请求 */
export interface CreateSummaryTaskRequest {
  topic_id: number | null
  time_span_hours: number
  deadline: string
  custom_prompt?: string | null
}
