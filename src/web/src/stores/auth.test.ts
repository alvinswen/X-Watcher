/** Auth Store 单元测试。 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { createPinia, setActivePinia } from "pinia"

vi.mock("@/api/client", () => ({
  setApiKeyProvider: vi.fn(),
}))

import { useAuthStore } from "./auth"
import { setApiKeyProvider } from "@/api/client"

describe("Auth Store", () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
    vi.mocked(setApiKeyProvider).mockClear()
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  describe("setApiKey", () => {
    it("设置后 store.apiKey 应更新为对应值", () => {
      const store = useAuthStore()
      store.setApiKey("my-secret-key")
      expect(store.apiKey).toBe("my-secret-key")
    })

    it("设置后 localStorage 应同步写入", () => {
      const store = useAuthStore()
      store.setApiKey("my-secret-key")
      expect(localStorage.getItem("admin_api_key")).toBe("my-secret-key")
    })
  })

  describe("clearApiKey", () => {
    it("清除后 store.apiKey 应为 null", () => {
      const store = useAuthStore()
      store.setApiKey("my-secret-key")
      store.clearApiKey()
      expect(store.apiKey).toBeNull()
    })

    it("清除后 localStorage 中对应键应被删除", () => {
      const store = useAuthStore()
      store.setApiKey("my-secret-key")
      store.clearApiKey()
      expect(localStorage.getItem("admin_api_key")).toBeNull()
    })
  })

  describe("isAuthenticated", () => {
    it("有 API Key 时应为 true", () => {
      const store = useAuthStore()
      store.setApiKey("some-key")
      expect(store.isAuthenticated).toBe(true)
    })

    it("无 API Key 时应为 false", () => {
      const store = useAuthStore()
      expect(store.isAuthenticated).toBe(false)
    })

    it("清除 API Key 后应变为 false", () => {
      const store = useAuthStore()
      store.setApiKey("some-key")
      store.clearApiKey()
      expect(store.isAuthenticated).toBe(false)
    })
  })

  describe("loadFromStorage", () => {
    it("localStorage 有值时应恢复到 store", () => {
      localStorage.setItem("admin_api_key", "stored-key")
      const store = useAuthStore()
      // store 初始化时已自动调用 loadFromStorage，因此直接验证
      expect(store.apiKey).toBe("stored-key")
    })

    it("手动调用 loadFromStorage 应从 localStorage 恢复", () => {
      const store = useAuthStore()
      expect(store.apiKey).toBeNull()
      localStorage.setItem("admin_api_key", "late-stored-key")
      store.loadFromStorage()
      expect(store.apiKey).toBe("late-stored-key")
    })

    it("localStorage 无值时 store.apiKey 应保持 null", () => {
      const store = useAuthStore()
      store.loadFromStorage()
      expect(store.apiKey).toBeNull()
    })
  })

  describe("初始化行为", () => {
    it("store 创建时应自动调用 setApiKeyProvider", () => {
      useAuthStore()
      expect(setApiKeyProvider).toHaveBeenCalledTimes(1)
      expect(setApiKeyProvider).toHaveBeenCalledWith(expect.any(Function))
    })

    it("注册的 provider 应返回当前 apiKey 值", () => {
      const store = useAuthStore()
      const provider = vi.mocked(setApiKeyProvider).mock.calls[0][0] as () => string | null
      // 初始无 key
      expect(provider()).toBeNull()
      // 设置 key 后 provider 应返回新值
      store.setApiKey("dynamic-key")
      expect(provider()).toBe("dynamic-key")
    })
  })
})
