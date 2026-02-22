/** 聚类分析 API 客户端。 */

import { client } from "./client"
import type {
  ClusterAssignment,
  ClusteringRunDetail,
  ClusteringRunSummary,
  DistributionsResponse,
  MoveAccountRequest,
  ReCutRequest,
  RunClusteringRequest,
} from "@/types/clustering"

const PREFIX = "/admin/analytics"

export const clusteringApi = {
  async getDistributions(minTweets?: number): Promise<DistributionsResponse> {
    const params = minTweets ? { min_tweets: minTweets } : {}
    const response = await client.get<DistributionsResponse>(`${PREFIX}/distributions`, { params })
    return response.data
  },

  async runClustering(request?: RunClusteringRequest): Promise<ClusteringRunDetail> {
    const response = await client.post<ClusteringRunDetail>(`${PREFIX}/clustering`, request || {})
    return response.data
  },

  async listRuns(): Promise<ClusteringRunSummary[]> {
    const response = await client.get<ClusteringRunSummary[]>(`${PREFIX}/clustering`)
    return response.data
  },

  async getLatest(): Promise<ClusteringRunDetail> {
    const response = await client.get<ClusteringRunDetail>(`${PREFIX}/clustering/latest`)
    return response.data
  },

  async getRun(runId: number): Promise<ClusteringRunDetail> {
    const response = await client.get<ClusteringRunDetail>(`${PREFIX}/clustering/${runId}`)
    return response.data
  },

  async reCut(runId: number, request: ReCutRequest): Promise<ClusteringRunDetail> {
    const response = await client.post<ClusteringRunDetail>(
      `${PREFIX}/clustering/${runId}/re-cut`,
      request,
    )
    return response.data
  },

  async moveAccount(
    runId: number,
    username: string,
    request: MoveAccountRequest,
  ): Promise<ClusterAssignment> {
    const response = await client.put<ClusterAssignment>(
      `${PREFIX}/clustering/${runId}/assignments/${username}`,
      request,
    )
    return response.data
  },

  async deleteRun(runId: number): Promise<void> {
    await client.delete(`${PREFIX}/clustering/${runId}`)
  },
}
