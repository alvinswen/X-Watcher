/** 5 个新增 API 模块的集成测试。 */

import { describe, it, expect, beforeEach, vi } from "vitest"
import type { Mocked } from "vitest"
import type { AxiosInstance } from "axios"

// --- Mock 策略 1: client（scheduler / users / summaries / dedup 共用） ---
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
import { schedulerApi } from "./scheduler"
import { usersApi } from "./users"
import { healthApi } from "./health"
import { summariesApi } from "./summaries"
import { dedupApi } from "./dedup"

const mockedClient = client as Mocked<Pick<AxiosInstance, "get" | "post" | "put">>
const mockedAxios = axios as Mocked<Pick<typeof axios, "get">>

// ============================================================
// schedulerApi
// ============================================================
describe("schedulerApi - 调度管理 API", () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it("getConfig 应发送 GET 请求到 /admin/scraping/schedule", async () => {
    const mockData = {
      interval_seconds: 3600,
      next_run_time: "2025-01-01T00:00:00Z",
      scheduler_running: true,
      job_active: true,
      is_enabled: true,
      updated_at: null,
      updated_by: null,
      message: null,
    }
    mockedClient.get.mockResolvedValueOnce({ data: mockData })

    const result = await schedulerApi.getConfig()

    expect(mockedClient.get).toHaveBeenCalledWith("/admin/scraping/schedule")
    expect(result).toEqual(mockData)
  })

  it("updateInterval 应发送 PUT 请求到 /admin/scraping/schedule/interval 并携带请求体", async () => {
    const requestData = { interval_seconds: 3600 }
    const mockData = {
      interval_seconds: 3600,
      next_run_time: null,
      scheduler_running: true,
      job_active: true,
      is_enabled: true,
      updated_at: "2025-01-01T00:00:00Z",
      updated_by: "admin",
      message: null,
    }
    mockedClient.put.mockResolvedValueOnce({ data: mockData })

    const result = await schedulerApi.updateInterval(requestData)

    expect(mockedClient.put).toHaveBeenCalledWith(
      "/admin/scraping/schedule/interval",
      requestData,
    )
    expect(result).toEqual(mockData)
  })

  it("updateNextRun 应发送 PUT 请求到 /admin/scraping/schedule/next-run 并携带请求体", async () => {
    const requestData = { next_run_time: "2025-06-01T12:00:00Z" }
    const mockData = {
      interval_seconds: 3600,
      next_run_time: "2025-06-01T12:00:00Z",
      scheduler_running: true,
      job_active: true,
      is_enabled: true,
      updated_at: "2025-01-01T00:00:00Z",
      updated_by: "admin",
      message: null,
    }
    mockedClient.put.mockResolvedValueOnce({ data: mockData })

    const result = await schedulerApi.updateNextRun(requestData)

    expect(mockedClient.put).toHaveBeenCalledWith(
      "/admin/scraping/schedule/next-run",
      requestData,
    )
    expect(result).toEqual(mockData)
  })

  it("enable 应发送 POST 请求到 /admin/scraping/schedule/enable", async () => {
    const mockData = {
      interval_seconds: 3600,
      next_run_time: "2025-01-01T01:00:00Z",
      scheduler_running: true,
      job_active: true,
      is_enabled: true,
      updated_at: "2025-01-01T00:00:00Z",
      updated_by: "admin",
      message: "调度已启用",
    }
    mockedClient.post.mockResolvedValueOnce({ data: mockData })

    const result = await schedulerApi.enable()

    expect(mockedClient.post).toHaveBeenCalledWith(
      "/admin/scraping/schedule/enable",
    )
    expect(result).toEqual(mockData)
  })

  it("disable 应发送 POST 请求到 /admin/scraping/schedule/disable", async () => {
    const mockData = {
      interval_seconds: 3600,
      next_run_time: null,
      scheduler_running: true,
      job_active: false,
      is_enabled: false,
      updated_at: "2025-01-01T00:00:00Z",
      updated_by: "admin",
      message: "调度已禁用",
    }
    mockedClient.post.mockResolvedValueOnce({ data: mockData })

    const result = await schedulerApi.disable()

    expect(mockedClient.post).toHaveBeenCalledWith(
      "/admin/scraping/schedule/disable",
    )
    expect(result).toEqual(mockData)
  })
})

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
        scheduler: { status: "healthy" as const },
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

// ============================================================
// dedupApi
// ============================================================
describe("dedupApi - 去重 API", () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it("batchDeduplicate 应发送 POST 请求到 /deduplicate/batch 并携带请求体", async () => {
    const tweetIds = ["t-1", "t-2"]
    const mockData = { task_id: "dedup-task-1", status: "pending" }
    mockedClient.post.mockResolvedValueOnce({ data: mockData })

    const result = await dedupApi.batchDeduplicate(tweetIds)

    expect(mockedClient.post).toHaveBeenCalledWith("/deduplicate/batch", {
      tweet_ids: tweetIds,
    })
    expect(result).toEqual(mockData)
  })

  it("getTaskStatus 应发送 GET 请求到 /deduplicate/tasks/:id", async () => {
    const mockData = {
      task_id: "task-1",
      status: "running",
      result: null,
      error: null,
      created_at: "2025-01-01T00:00:00Z",
      started_at: "2025-01-01T00:00:01Z",
      completed_at: null,
      progress: { current: 1, total: 2, percentage: 50 },
      metadata: {},
    }
    mockedClient.get.mockResolvedValueOnce({ data: mockData })

    const result = await dedupApi.getTaskStatus("task-1")

    expect(mockedClient.get).toHaveBeenCalledWith("/deduplicate/tasks/task-1")
    expect(result).toEqual(mockData)
  })
})
