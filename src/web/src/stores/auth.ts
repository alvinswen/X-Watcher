/** Auth Store - 统一管理 API Key 认证状态 */

import { defineStore } from "pinia"
import { ref, computed } from "vue"
import { setApiKeyProvider, setUnauthorizedHandler } from "@/api/client"
import { messageService } from "@/services/message"

/** localStorage 键名（与 client.ts 保持一致） */
const API_KEY_STORAGE_KEY = "admin_api_key"

export const useAuthStore = defineStore("auth", () => {
  /** API Key */
  const apiKey = ref<string | null>(null)

  /** 是否已认证（API Key 已配置） */
  const isAuthenticated = computed(() => !!apiKey.value)

  /** API Key 设置对话框是否可见 */
  const dialogVisible = ref(false)

  /** 当前 API Key 是否被服务端判定为无效 */
  const keyInvalid = ref(false)

  /** 本会话是否已自动展示过配置引导 */
  const guideAutoShown = ref(false)

  /** 设置 API Key 并保存到 localStorage */
  function setApiKey(key: string) {
    apiKey.value = key
    keyInvalid.value = false
    localStorage.setItem(API_KEY_STORAGE_KEY, key)
  }

  /** 清除 API Key */
  function clearApiKey() {
    apiKey.value = null
    keyInvalid.value = false
    localStorage.removeItem(API_KEY_STORAGE_KEY)
  }

  /** 打开 API Key 设置对话框 */
  function openDialog() {
    keyInvalid.value = false
    dialogVisible.value = true
  }

  /** 本会话内仅自动展示一次配置引导 */
  function requestGuide() {
    if (guideAutoShown.value) return
    guideAutoShown.value = true
    dialogVisible.value = true
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
  setUnauthorizedHandler((hasKey) => {
    if (!hasKey || keyInvalid.value) return
    keyInvalid.value = true
    messageService.errorWithAction(
      "API Key 无效，请重新配置",
      "重新配置",
      openDialog,
    )
  })

  return {
    apiKey,
    isAuthenticated,
    dialogVisible,
    keyInvalid,
    guideAutoShown,
    setApiKey,
    clearApiKey,
    loadFromStorage,
    openDialog,
    requestGuide,
  }
})
