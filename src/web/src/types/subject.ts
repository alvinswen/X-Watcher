/** Subject 议题类型。 */

import type { TweetCardData } from "./tweet"

export type SubjectStatus = "active" | "paused"

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
  last_classified_at?: string | null
}

export interface SubjectDigestHighlight {
  point: string
  cited_tweet_ids: string[]
}

export interface SubjectDigest {
  subject_id: string
  interval_start: string
  interval_end: string
  time_axis: string
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

export interface SubjectReviewSection {
  title: string
  body: string
  cited_tweet_ids: string[]
}

export interface SubjectReviewTrend {
  emerging: string[]
  fading: string[]
}

export interface SubjectReview {
  subject_id: string
  version: number
  sections: SubjectReviewSection[]
  trend: SubjectReviewTrend
  cited_tweet_ids: string[]
  prev_version?: number | null
  generated_at?: string | null
  generated_by?: "llm" | "fallback" | "skill" | null
  covered_until?: string | null
  updated_at?: string | null
  cited_tweets: TweetCardData[]
  missing_tweet_ids: string[]
}

export interface SubjectReviewRefreshResponse {
  task_id: string | null
  pending?: boolean
  message: string
}
