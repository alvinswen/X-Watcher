/** 候选信源评审接口的手工镜像类型。 */

import type { MediaItem, TweetCardData } from "./tweet"

export type CandidateStatus = "discovered" | "assessed" | "approved" | "rejected"

export type CandidateStatusFilter = "pending" | "all" | CandidateStatus

export interface CitationSignal {
  count: number
  citing_tweet_ids: string[]
}

export interface CandidateMining {
  citations: Record<string, CitationSignal>
  citation_total: number
  source_diversity: number
  sample_citation_tweet_ids: string[]
  subject_tags: string[]
  first_discovered_at: string
  last_mined_at: string
}

export interface CandidateProfileSnapshot {
  platform_user_id: string
  username: string
  display_name: string | null
  is_blue_verified: boolean
  verified_type: string | null
  profile_picture: string | null
  cover_picture: string | null
  description: string | null
  location: string | null
  followers_count: number | null
  following_count: number | null
  statuses_count: number | null
  favourites_count: number | null
  media_count: number | null
  account_created_at: string | null
  is_automated: boolean
  possibly_sensitive: boolean
  pinned_tweet_ids: string[] | null
  unavailable: boolean
  unavailable_reason: string | null
  fetched_at: string | null
}

export interface CandidateSampleTweet {
  tweet_id: string
  text: string
  created_at: string
  author_username: string
  author_display_name: string | null
  author_user_id: string | null
  referenced_tweet_id: string | null
  reference_type: string | null
  media: MediaItem[] | null
  referenced_tweet_text: string | null
  referenced_tweet_media: MediaItem[] | null
  referenced_tweet_author_username: string | null
  article_preview: Record<string, unknown> | null
}

export interface CandidateSample {
  tweets: CandidateSampleTweet[]
  fetched_at: string
}

export interface CandidateScores {
  originality: number
  difference: number
  expertise: number
}

export interface CandidateAssessment {
  scores: CandidateScores
  recommendation: string
  evidence_tweet_ids: string[]
  assessed_at: string
  assessed_by: string
}

export interface CandidateDecision {
  verdict: "approve" | "reject"
  decided_by: string
  decided_at: string
  reject_reason: string | null
  follow_id: number | null
  follow_username: string | null
}

export interface CandidateDossier {
  candidate_id: string
  username: string
  platform_user_id: string | null
  status: CandidateStatus | string
  mining: CandidateMining
  profile_snapshot: CandidateProfileSnapshot | null
  profile_fetched_at: string | null
  sample: CandidateSample | null
  assessment: CandidateAssessment | null
  decision: CandidateDecision | null
}

export interface CandidateSummary {
  candidate_id: string
  username: string
  platform_user_id: string | null
  status: CandidateStatus | string
  citation_total: number
  source_diversity: number
  subject_tags: string[]
  first_discovered_at: string
  last_mined_at: string
  sample_fetched_at: string | null
  assessed_at: string | null
  decided_at: string | null
  display_name: string | null
  verified_type: string | null
  is_automated: boolean | null
}

export interface CandidateListResponse {
  candidates: CandidateSummary[]
  count: number
  total: number
  page: number
  page_size: number
}

export interface CandidateDetailResponse {
  candidate: CandidateDossier
  sample_citation_tweets: TweetCardData[]
  missing_citation_tweet_ids: string[]
}

export interface CandidateReviewRequest {
  decision: "approve" | "reject"
  brief_intro?: string | null
  reject_reason?: string | null
}

export interface CandidateReviewResponse {
  candidate_id: string
  status: CandidateStatus | string
  follow_id: number | null
  follow_username: string | null
  platform_user_id: string | null
  notice: string | null
}

export function sampleTweetToCardData(tweet: CandidateSampleTweet): TweetCardData {
  return {
    tweet_id: tweet.tweet_id,
    text: tweet.text,
    created_at: tweet.created_at,
    author_username: tweet.author_username,
    author_display_name: tweet.author_display_name,
    summary_text: null,
    translation_text: null,
    media: tweet.media,
    reference_type: tweet.reference_type,
    referenced_tweet_id: tweet.referenced_tweet_id,
    referenced_tweet_text: tweet.referenced_tweet_text,
    referenced_tweet_author_username: tweet.referenced_tweet_author_username,
    referenced_tweet_media: tweet.referenced_tweet_media,
  }
}
