/** Subject 议题类型。 */

export type SubjectStatus = "active" | "paused"

export interface SubjectTaskSnapshot {
  task_id: string
  status: "pending" | "running" | "completed" | "failed" | string
  progress?: {
    current: number
    total: number
    percentage: number
  }
  error?: string | null
  result?: Record<string, unknown> | null
}

export interface Subject {
  subject_id: string
  name: string
  nl_description: string
  keywords: string[]
  status: SubjectStatus
  created_at: string
  updated_at: string
  last_updated_at?: string | null
  match_count: number
  backfill_task_id?: string | null
  backfill_task?: SubjectTaskSnapshot | null
}

export interface SubjectCreateRequest {
  name: string
  nl_description: string
  keywords?: string[]
}

export interface SubjectUpdateRequest {
  name?: string
  nl_description?: string
  keywords?: string[]
  status?: SubjectStatus
}

export interface SubjectFeedItem {
  tweet_id: string
  text: string
  summary?: string | null
  translation?: string | null
  author?: string | null
  author_username?: string | null
  created_at: string
}

export interface SubjectFeedResponse {
  items: SubjectFeedItem[]
  count: number
  has_more: boolean
  next_since?: string | null
}

export interface SubjectDigestHighlight {
  point: string
  cited_tweet_ids: string[]
}

export interface SubjectDigest {
  subject_id: string
  hour: string
  tweet_count: number
  digest_text: string
  highlights: SubjectDigestHighlight[]
  cited_tweet_ids: string[]
  generated_at: string
}

export interface SubjectDigestResponse {
  items: SubjectDigest[]
  count: number
}
