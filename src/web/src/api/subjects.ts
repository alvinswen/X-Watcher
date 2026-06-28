/** Subject 议题 API 客户端。 */

import { client } from "./client"
import type {
  Subject,
  SubjectCreateRequest,
  SubjectDigestResponse,
  SubjectFeedResponse,
  SubjectReview,
  SubjectReviewRefreshResponse,
  SubjectStatus,
  SubjectUpdateRequest,
} from "@/types"

const SUBJECTS_PREFIX = "/admin/subjects"

export const subjectsApi = {
  async list(status?: SubjectStatus): Promise<Subject[]> {
    const response = await client.get<Subject[]>(SUBJECTS_PREFIX, {
      params: status ? { status } : undefined,
    })
    return response.data
  },

  async create(request: SubjectCreateRequest): Promise<Subject> {
    const response = await client.post<Subject>(SUBJECTS_PREFIX, request)
    return response.data
  },

  async get(subjectId: string): Promise<Subject> {
    const response = await client.get<Subject>(`${SUBJECTS_PREFIX}/${subjectId}`)
    return response.data
  },

  async update(subjectId: string, request: SubjectUpdateRequest): Promise<Subject> {
    const response = await client.put<Subject>(`${SUBJECTS_PREFIX}/${subjectId}`, request)
    return response.data
  },

  async delete(subjectId: string): Promise<void> {
    await client.delete(`${SUBJECTS_PREFIX}/${subjectId}`)
  },

  async feed(subjectId: string): Promise<SubjectFeedResponse> {
    const response = await client.get<SubjectFeedResponse>(`${SUBJECTS_PREFIX}/${subjectId}/feed`)
    return response.data
  },

  async digests(subjectId: string): Promise<SubjectDigestResponse> {
    const response = await client.get<SubjectDigestResponse>(`${SUBJECTS_PREFIX}/${subjectId}/digests`)
    return response.data
  },

  async review(subjectId: string): Promise<SubjectReview> {
    const response = await client.get<SubjectReview>(`${SUBJECTS_PREFIX}/${subjectId}/review`)
    return response.data
  },

  async refreshReview(subjectId?: string): Promise<SubjectReviewRefreshResponse> {
    const url = subjectId
      ? `${SUBJECTS_PREFIX}/${subjectId}/review/refresh`
      : `${SUBJECTS_PREFIX}/review/refresh`
    const response = await client.post<SubjectReviewRefreshResponse>(url)
    return response.data
  },
}
