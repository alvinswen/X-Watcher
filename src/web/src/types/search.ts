/** 推文搜索相关类型定义。 */

/** 搜索参数 */
export interface SearchParams {
  q: string
  author?: string
  since?: string
  until?: string
  page?: number
  page_size?: number
  include_summary?: boolean
}

/** 搜索结果推文条目 */
export interface SearchTweetItem {
  tweet_id: string
  text: string
  author_username: string
  author_display_name: string | null
  created_at: string
  db_created_at: string
  reference_type: string | null
  referenced_tweet_id: string | null
  referenced_tweet_text: string | null
  referenced_tweet_author_username: string | null
  media: Record<string, unknown>[] | null
  referenced_tweet_media: Record<string, unknown>[] | null
  summary_text: string | null
  translation_text: string | null
}

/** 搜索响应 */
export interface SearchResponse {
  items: SearchTweetItem[]
  count: number
  total: number
  page: number
  page_size: number
  total_pages: number
  q: string
}
