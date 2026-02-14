/** Auth Store - 统一管理 API Key 认证状态 */

import { defineStore } from "pinia"
import { ref, computed } from "vue"
import { setApiKeyProvider } from "@/api/client"

/** localStorage 键名（与 client.ts 保持一致） */
const API_KEY_STORAGE_KEY = "admin_api_key"

export const useAuthStore = defineStore("auth", () => {
  /** API Key */
  const apiKey = ref<string | null>(null)

  /** 是否已认证（API Key 已配置） */
  const isAuthenticated = computed(() => !!apiKey.value)

  /** 设置 API Key 并保存到 localStorage */
  function setApiKey(key: string) {
    apiKey.value = key
    localStorage.setItem(API_KEY_STORAGE_KEY, key)
  }

  /** 清除 API Key */
  function clearApiKey() {
    apiKey.value = null
    localStorage.removeItem(API_KEY_STORAGE_KEY)
  }

  /** 从 localStorage 恢复状态 */
  function loadFromStorage() {
    const stored = localStorage.getItem(API_KEY_STORAGE_KEY)
    if (stored) {
      apiKey.value = stored
    }
  }

  // 初始化时自动恢复状态并注册 provider
  loadFromStorage()
  setApiKeyProvider(() => apiKey.value)

  return {
    apiKey,
    isAuthenticated,
    setApiKey,
    clearApiKey,
    loadFromStorage,
  }
})
