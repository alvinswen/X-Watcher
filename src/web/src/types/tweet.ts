/** 推文相关类型定义。 */

/** 推文列表项。 */
export interface TweetListItem {
  /** 推文 ID */
  tweet_id: string
  /** 推文内容 */
  text: string
  /** 作者用户名 */
  author_username: string
  /** 作者显示名称 */
  author_display_name: string | null
  /** 推文创建时间 */
  created_at: string
  /** 入库时间 */
  db_created_at: string
  /** 引用类型 */
  reference_type: string | null
  /** 引用的推文 ID */
  referenced_tweet_id: string | null
  /** 是否有摘要 */
  has_summary: boolean
  /** 媒体数量 */
  media_count: number
}

/** 推文详情。 */
export interface TweetDetail extends TweetListItem {
  /** 媒体附件 */
  media: MediaItem[] | null
  /** 摘要信息 */
  summary: Summary | null
}

/** 媒体项。 */
export interface MediaItem {
  /** 媒体类型 */
  type: string
  /** 媒体 URL */
  url: string
  /** 媒体宽度 */
  width?: number
  /** 媒体高度 */
  height?: number
}

/** 摘要信息。 */
export interface Summary {
  /** 摘要 ID */
  summary_id: string
  /** 摘要文本 */
  summary_text: string
  /** 翻译文本 */
  translation_text: string | null
  /** 模型提供商 */
  model_provider: string
  /** 模型名称 */
  model_name: string
  /** 成本（美元） */
  cost_usd: number
  /** 是否缓存 */
  cached: boolean
  /** 是否为生成的摘要 */
  is_generated_summary: boolean
  /** 创建时间 */
  created_at: string | null
}

/** 推文列表响应。 */
export interface TweetListResponse {
  /** 推文列表 */
  items: TweetListItem[]
  /** 总数量 */
  total: number
  /** 当前页码 */
  page: number
  /** 每页数量 */
  page_size: number
  /** 总页数 */
  total_pages: number
}

/** 推文列表查询参数。 */
export interface TweetListParams {
  /** 页码（从 1 开始） */
  page?: number
  /** 每页数量（1-100） */
  page_size?: number
  /** 按作者用户名筛选 */
  author?: string
}
