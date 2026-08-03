/** 候选信源评审 API 客户端。 */

import { client } from "./client"
import type {
  CandidateDetailResponse,
  CandidateListResponse,
  CandidateReviewRequest,
  CandidateReviewResponse,
} from "@/types"

const CANDIDATES_PREFIX = "/admin/source-candidates"

export const candidatesApi = {
  async list(params: {
    status?: string
    page?: number
    page_size?: number
  }): Promise<CandidateListResponse> {
    const response = await client.get<CandidateListResponse>(CANDIDATES_PREFIX, {
      params,
      suppressErrorToast: true,
    })
    return response.data
  },

  async detail(candidateId: string): Promise<CandidateDetailResponse> {
    const response = await client.get<CandidateDetailResponse>(
      `${CANDIDATES_PREFIX}/${candidateId}`,
      { suppressErrorToast: true },
    )
    return response.data
  },

  async review(
    candidateId: string,
    request: CandidateReviewRequest,
  ): Promise<CandidateReviewResponse> {
    const response = await client.post<CandidateReviewResponse>(
      `${CANDIDATES_PREFIX}/${candidateId}/review`,
      request,
      { suppressErrorToast: true },
    )
    return response.data
  },
}
