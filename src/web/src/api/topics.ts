/** 主题管理 API 客户端。 */

import { client } from "./client"
import type {
  TopicListItem,
  TopicDetail,
  Topic,
  TopicAccount,
  CreateTopicRequest,
  UpdateTopicRequest,
  SetAccountsRequest,
  TopicSummaryTask,
  TopicSummaryTaskDetail,
  CreateSummaryTaskRequest,
  ImagePromptResponse,
  LatestSummaryResponse,
} from "@/types/topic"

const TOPICS_PREFIX = "/topics"
const SUMMARY_TASKS_PREFIX = "/topics/summary-tasks"

export const topicsApi = {
  // ── 主题 CRUD ──

  async list(): Promise<TopicListItem[]> {
    const response = await client.get<TopicListItem[]>(TOPICS_PREFIX)
    return response.data
  },

  async get(id: number): Promise<TopicDetail> {
    const response = await client.get<TopicDetail>(`${TOPICS_PREFIX}/${id}`)
    return response.data
  },

  async create(request: CreateTopicRequest): Promise<Topic> {
    const response = await client.post<Topic>(TOPICS_PREFIX, request)
    return response.data
  },

  async update(id: number, request: UpdateTopicRequest): Promise<Topic> {
    const response = await client.put<Topic>(`${TOPICS_PREFIX}/${id}`, request)
    return response.data
  },

  async delete(id: number): Promise<void> {
    await client.delete(`${TOPICS_PREFIX}/${id}`)
  },

  // ── 账号管理 ──

  async setAccounts(topicId: number, request: SetAccountsRequest): Promise<TopicAccount[]> {
    const response = await client.put<TopicAccount[]>(
      `${TOPICS_PREFIX}/${topicId}/accounts`,
      request,
    )
    return response.data
  },

  async addAccount(topicId: number, username: string): Promise<TopicAccount> {
    const response = await client.post<TopicAccount>(
      `${TOPICS_PREFIX}/${topicId}/accounts/${username}`,
    )
    return response.data
  },

  async removeAccount(topicId: number, username: string): Promise<void> {
    await client.delete(`${TOPICS_PREFIX}/${topicId}/accounts/${username}`)
  },

  // ── 摘要任务 ──

  async getDefaultPrompt(): Promise<{ prompt: string }> {
    const response = await client.get<{ prompt: string }>(`${SUMMARY_TASKS_PREFIX}/default-prompt`)
    return response.data
  },

  async listTasks(topicId?: number): Promise<TopicSummaryTask[]> {
    const params = topicId ? { topic_id: topicId } : {}
    const response = await client.get<TopicSummaryTask[]>(SUMMARY_TASKS_PREFIX, { params })
    return response.data
  },

  async getTask(taskId: number): Promise<TopicSummaryTaskDetail> {
    const response = await client.get<TopicSummaryTaskDetail>(
      `${SUMMARY_TASKS_PREFIX}/${taskId}`,
    )
    return response.data
  },

  async createTask(request: CreateSummaryTaskRequest): Promise<TopicSummaryTask> {
    const response = await client.post<TopicSummaryTask>(SUMMARY_TASKS_PREFIX, request)
    return response.data
  },

  async deleteTask(taskId: number): Promise<void> {
    await client.delete(`${SUMMARY_TASKS_PREFIX}/${taskId}`)
  },

  async generateImagePrompt(taskId: number): Promise<ImagePromptResponse> {
    const response = await client.post<ImagePromptResponse>(
      `${SUMMARY_TASKS_PREFIX}/${taskId}/generate-image-prompt`,
    )
    return response.data
  },

  // ── 最新摘要 ──

  async getLatestSummary(topicId: number): Promise<LatestSummaryResponse> {
    const response = await client.get<LatestSummaryResponse>(
      `${TOPICS_PREFIX}/${topicId}/latest-summary`,
    )
    return response.data
  },
}
