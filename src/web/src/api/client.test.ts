/** API Client 单元测试。 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { setApiKey, getApiKey, clearApiKey } from "./client"

describe("API Client - API Key 管理", () => {
  beforeEach(() => {
    localStorage.clear()
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it("应该能够设置 API Key", () => {
    setApiKey("test-api-key")
    expect(localStorage.getItem("admin_api_key")).toBe("test-api-key")
  })

  it("应该能够获取已设置的 API Key", () => {
    setApiKey("test-api-key")
    expect(getApiKey()).toBe("test-api-key")
  })

  it("当 API Key 不存在时，getApiKey 应该返回 null", () => {
    expect(getApiKey()).toBeNull()
  })

  it("应该能够清除 API Key", () => {
    setApiKey("test-api-key")
    clearApiKey()
    expect(getApiKey()).toBeNull()
  })

  it("应该能够覆盖已存在的 API Key", () => {
    setApiKey("first-key")
    setApiKey("second-key")
    expect(getApiKey()).toBe("second-key")
  })
})
