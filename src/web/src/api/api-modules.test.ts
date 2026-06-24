/** API 模块集成测试。 */

import { describe, it, expect, beforeEach, vi } from "vitest"
import type { Mocked } from "vitest"
import type { AxiosInstance } from "axios"

// --- Mock 策略 1: client（users / summaries 共用） ---
vi.mock("./client", () => {
  const client = {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  }
  return { client }
})

// --- Mock 策略 2: axios（health 独立使用） ---
vi.mock("axios", () => {
  return {
    default: { get: vi.fn() },
    __esModule: true,
  }
})

// 导入被测模块（必须在 vi.mock 之后）
import { client } from "./client"
import axios from "axios"
import { usersApi } from "./users"
import { healthApi } from "./health"
import { summariesApi } from "./summaries"

const mockedClient = client as Mocked<Pick<AxiosInstance, "get" | "post" | "put">>
const mockedAxios = axios as Mocked<Pick<typeof axios, "get">>

// ============================================================
// usersApi
// ============================================================
describe("usersApi - 用户管理 API", () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it("list 应发送 GET 请求到 /admin/users", async () => {
    const mockData: Array<{
      id: number
      name: string
      email: string
      is_admin: boolean
      created_at: string
    }> = [
      {
        id: 1,
        name: "admin",
        email: "admin@example.com",
        is_admin: true,
        created_at: "2025-01-01T00:00:00Z",
      },
    ]
    mockedClient.get.mockResolvedValueOnce({ data: mockData })

    const result = await usersApi.list()

    expect(mockedClient.get).toHaveBeenCalledWith("/admin/users")
    expect(result).toEqual(mockData)
  })

  it("create 应发送 POST 请求到 /admin/users 并携带请求体", async () => {
    const requestData = { name: "test", email: "test@test.com" }
    const mockData = {
      user: {
        id: 2,
        name: "test",
        email: "test@test.com",
        is_admin: false,
        created_at: "2025-01-01T00:00:00Z",
      },
      temp_password: "abc123",
      api_key: "key-xyz",
    }
    mockedClient.post.mockResolvedValueOnce({ data: mockData })

    const result = await usersApi.create(requestData)

    expect(mockedClient.post).toHaveBeenCalledWith("/admin/users", requestData)
    expect(result).toEqual(mockData)
  })

  it("resetPassword 应发送 POST 请求到 /admin/users/:id/reset-password", async () => {
    const mockData = { temp_password: "new-pass-456" }
    mockedClient.post.mockResolvedValueOnce({ data: mockData })

    const result = await usersApi.resetPassword(1)

    expect(mockedClient.post).toHaveBeenCalledWith(
      "/admin/users/1/reset-password",
    )
    expect(result).toEqual(mockData)
  })
})

// ============================================================
// healthApi
// ============================================================
describe("healthApi - 健康检查 API", () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it("getStatus 应使用独立 axios 发送 GET 请求到 /health", async () => {
    const mockData = {
      status: "healthy" as const,
      components: {
        database: { status: "healthy" as const },
      },
    }
    mockedAxios.get.mockResolvedValueOnce({ data: mockData })

    const result = await healthApi.getStatus()

    expect(mockedAxios.get).toHaveBeenCalledWith("/health")
    expect(mockedClient.get).not.toHaveBeenCalled()
    expect(result).toEqual(mockData)
  })
})

// ============================================================
// summariesApi
// ============================================================
describe("summariesApi - 摘要 API", () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it("getStats 应发送 GET 请求到 /summaries/stats 并携带查询参数", async () => {
    const params = { start_date: "2025-01-01", end_date: "2025-01-31" }
    const mockData = {
      start_date: "2025-01-01",
      end_date: "2025-01-31",
      total_cost_usd: 1.5,
      total_tokens: 10000,
      prompt_tokens: 7000,
      completion_tokens: 3000,
      provider_breakdown: {},
    }
    mockedClient.get.mockResolvedValueOnce({ data: mockData })

    const result = await summariesApi.getStats(params)

    expect(mockedClient.get).toHaveBeenCalledWith("/summaries/stats", {
      params,
    })
    expect(result).toEqual(mockData)
  })

  it("batchSummarize 应发送 POST 请求到 /summaries/batch 并携带请求体", async () => {
    const tweetIds = ["t-1", "t-2", "t-3"]
    const mockData = { task_id: "task-abc", status: "pending" }
    mockedClient.post.mockResolvedValueOnce({ data: mockData })

    const result = await summariesApi.batchSummarize(tweetIds, true)

    expect(mockedClient.post).toHaveBeenCalledWith("/summaries/batch", {
      tweet_ids: tweetIds,
      force_refresh: true,
    })
    expect(result).toEqual(mockData)
  })

  it("regenerate 应发送 POST 请求到 /summaries/tweets/:id/regenerate", async () => {
    const mockData = { summary: "新摘要内容" }
    mockedClient.post.mockResolvedValueOnce({ data: mockData })

    const result = await summariesApi.regenerate("tweet-1")

    expect(mockedClient.post).toHaveBeenCalledWith(
      "/summaries/tweets/tweet-1/regenerate",
    )
    expect(result).toEqual(mockData)
  })

  it("getTaskStatus 应发送 GET 请求到 /summaries/tasks/:id", async () => {
    const mockData = {
      task_id: "task-1",
      status: "completed",
      result: { processed: 3 },
      error: null,
      created_at: "2025-01-01T00:00:00Z",
      started_at: "2025-01-01T00:00:01Z",
      completed_at: "2025-01-01T00:00:05Z",
      progress: { current: 3, total: 3, percentage: 100 },
      metadata: {},
    }
    mockedClient.get.mockResolvedValueOnce({ data: mockData })

    const result = await summariesApi.getTaskStatus("task-1")

    expect(mockedClient.get).toHaveBeenCalledWith("/summaries/tasks/task-1")
    expect(result).toEqual(mockData)
  })
})
