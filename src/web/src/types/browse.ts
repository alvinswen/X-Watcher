/** 推文浏览相关类型定义。 */

/** 每日推文数量 */
export interface DailyCount {
  date: string
  count: number
}

/** 每日统计响应 */
export interface DailyStatsResponse {
  year: number
  month: number
  days: DailyCount[]
}

/** 作者信息 */
export interface AuthorInfo {
  author_username: string
  author_display_name: string | null
  tweet_count: number
  last_tweet_at: string
  reason: string | null
}

/** 作者列表响应 */
export interface AuthorListResponse {
  authors: AuthorInfo[]
  total: number
}

/** 推文浏览条目 */
export interface BrowseTweetItem {
  tweet_id: string
  created_at: string
  author_username: string
  author_display_name: string | null
  summary_text: string | null
  translation_text: string | null
  text: string
  reference_type: string | null
  referenced_tweet_id: string | null
  referenced_tweet_text: string | null
  referenced_tweet_author_username: string | null
  media: Record<string, unknown>[] | null
  referenced_tweet_media: Record<string, unknown>[] | null
}

/** 推文浏览列表响应 */
export interface BrowseTweetListResponse {
  items: BrowseTweetItem[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

/** 推文浏览列表请求参数 */
export interface BrowseTweetListParams {
  date: string
  author?: string
  page?: number
  page_size?: number
  min_text_length?: number
}

/** 作者时间线请求参数 */
export interface AuthorTimelineParams {
  author: string
  since: string
  until: string
  page?: number
  page_size?: number
  min_text_length?: number
}

/** 作者时间线响应 */
export interface AuthorTimelineResponse {
  author_username: string
  author_display_name: string | null
  reason: string | null
  items: BrowseTweetItem[]
  total: number
  page: number
  page_size: number
  total_pages: number
}
