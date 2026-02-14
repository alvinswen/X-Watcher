/** API 客户端基础配置。 */

import axios, { AxiosError, type AxiosInstance, type AxiosRequestConfig, type AxiosResponse } from "axios"
import type { ApiError } from "@/types"
import { messageService } from "@/services/message"

/** API 基础 URL */
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api"

/** API Key 存储键名 */
const API_KEY_STORAGE_KEY = "admin_api_key"

/** API Key provider（由 Auth Store 注入） */
let apiKeyProvider: (() => string | null) | null = null

/** 注册 API Key provider（依赖注入，避免循环引用） */
export function setApiKeyProvider(provider: () => string | null): void {
  apiKeyProvider = provider
}

/** 创建 Axios 实例 */
const client: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    "Content-Type": "application/json",
  },
})

/** 请求拦截器 */
client.interceptors.request.use(
  (config) => {
    // 优先通过 provider 获取 API Key，fallback 到 localStorage
    const apiKey = apiKeyProvider ? apiKeyProvider() : localStorage.getItem(API_KEY_STORAGE_KEY)
    if (apiKey) {
      config.headers["X-API-Key"] = apiKey
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  },
)

/** 响应拦截器 */
client.interceptors.response.use(
  (response: AxiosResponse) => {
    return response
  },
  (error: AxiosError<ApiError>) => {
    // 统一处理错误
    let message = "请求失败"

    if (error.code === "ECONNABORTED" || error.message.includes("timeout")) {
      message = "请求超时，请检查网络连接"
    } else if (error.response) {
      const status = error.response.status
      const detail = error.response.data?.detail

      switch (status) {
        case 403:
          message = detail || "认证失败，请检查 API Key 配置"
          break
        case 404:
          message = detail || "资源不存在"
          break
        case 500:
          message = detail || "服务器错误，请稍后重试"
          break
        default:
          message = detail || `请求失败 (${status})`
      }
    } else if (error.message) {
      message = error.message
    }

    // 记录错误到控制台
    console.error("API 错误:", message, error)

    // 显示用户友好提示
    messageService.error(message)

    return Promise.reject(new Error(message))
  },
)

/** 设置 API Key */
export function setApiKey(key: string): void {
  localStorage.setItem(API_KEY_STORAGE_KEY, key)
}

/** 获取 API Key */
export function getApiKey(): string | null {
  return localStorage.getItem(API_KEY_STORAGE_KEY)
}

/** 清除 API Key */
export function clearApiKey(): void {
  localStorage.removeItem(API_KEY_STORAGE_KEY)
}

export { client }

/** 通用请求方法 */
export async function request<T>(config: AxiosRequestConfig): Promise<T> {
  const response = await client.request<T>({
    ...config,
    headers: {
      ...config.headers,
    },
  })
  return response.data
}
