/** 聚类分析类型定义。 */

export interface AccountDistribution {
  username: string
  distribution: number[]
  tweet_count: number
}

export interface DistributionsResponse {
  distributions: AccountDistribution[]
  excluded: string[]
}

export interface ClusterAssignment {
  id: number
  username: string
  cluster_id: number
  hourly_distribution: number[]
  tweet_count: number
  is_manual_override: boolean
}

export interface ClusteringRunSummary {
  id: number
  status: string
  num_clusters: number | null
  num_accounts: number | null
  num_excluded: number | null
  min_tweets_threshold: number
  linkage_method: string
  error_message: string | null
  created_at: string
  completed_at: string | null
}

export interface ClusteringRunDetail extends ClusteringRunSummary {
  cut_height: number | null
  linkage_matrix: number[][] | null
  account_labels: string[] | null
  assignments: ClusterAssignment[]
}

export interface RunClusteringRequest {
  min_tweets?: number
  linkage_method?: string
  cut_height?: number
  num_clusters?: number
}

export interface ReCutRequest {
  cut_height?: number
  num_clusters?: number
}

export interface MoveAccountRequest {
  cluster_id: number
}
