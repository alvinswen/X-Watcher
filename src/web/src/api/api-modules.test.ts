/** API 模块集成测试。 */

import { describe, it, expect, beforeEach, vi } from "vitest"
import type { Mocked } from "vitest"
import type { AxiosInstance } from "axios"

// --- Mock 策略 1: client（users 使用） ---
vi.mock("./client", () => {
  const client = {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  }
  return { client }
})

// 导入被测模块（必须在 vi.mock 之后）
import { client } from "./client"
import { usersApi } from "./users"

const mockedClient = client as Mocked<Pick<AxiosInstance, "get" | "post" | "put">>

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

    expect(mockedClient.post).toHaveBeenCalledWith(
      "/admin/users",
      requestData,
      { suppressErrorToast: true },
    )
    expect(result).toEqual(mockData)
  })

  it("resetPassword 应发送 POST 请求到 /admin/users/:id/reset-password", async () => {
    const mockData = { temp_password: "new-pass-456" }
    mockedClient.post.mockResolvedValueOnce({ data: mockData })

    const result = await usersApi.resetPassword(1)

    expect(mockedClient.post).toHaveBeenCalledWith(
      "/admin/users/1/reset-password",
      undefined,
      { suppressErrorToast: true },
    )
    expect(result).toEqual(mockData)
  })
})
