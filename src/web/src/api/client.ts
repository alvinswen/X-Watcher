/** API 客户端基础配置。 */

import axios, { AxiosError, type AxiosInstance, type AxiosResponse } from "axios"
import type { ApiError } from "@/types"
import { messageService } from "@/services/message"

declare module "axios" {
  export interface AxiosRequestConfig {
    suppressErrorToast?: boolean
  }
}

/** API 基础 URL */
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api"

/** API Key 存储键名 */
export const API_KEY_STORAGE_KEY = "admin_api_key"

/** API Key provider（由 Auth Store 注入） */
let apiKeyProvider: (() => string | null) | null = null

/** 401 处理器（由 Auth Store 注入） */
let unauthorizedHandler: ((hasKey: boolean) => void) | null = null

/** 保留 HTTP 失败上下文的前端请求错误。 */
export class ApiRequestError extends Error {
  readonly status: number | null
  readonly detail: string | null
  readonly isTimeout: boolean

  constructor(
    message: string,
    opts: {
      status?: number | null
      detail?: string | null
      isTimeout?: boolean
    } = {},
  ) {
    super(message)
    this.name = "ApiRequestError"
    this.status = opts.status ?? null
    this.detail = opts.detail ?? null
    this.isTimeout = opts.isTimeout ?? false
  }
}

/** 注册 API Key provider（依赖注入，避免循环引用） */
export function setApiKeyProvider(provider: () => string | null): void {
  apiKeyProvider = provider
}

/** 注册 401 处理器（依赖注入，避免循环引用） */
export function setUnauthorizedHandler(handler: (hasKey: boolean) => void): void {
  unauthorizedHandler = handler
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

/** 将 Axios 失败归一化为前端请求错误，并按请求配置决定是否提示。 */
export function handleApiError(error: AxiosError<ApiError>): Promise<never> {
  const isTimeout = error.code === "ECONNABORTED" || error.message.includes("timeout")
  const status = error.response?.status ?? null
  const detail = error.response?.data?.detail ?? null
  const suppressErrorToast = error.config?.suppressErrorToast === true
  let message: string

  if (isTimeout) {
    message = "请求超时，请检查网络连接"
  } else if (status !== null) {
    switch (status) {
      case 401: {
        const hasKey = Boolean(error.config?.headers?.["X-API-Key"])
        unauthorizedHandler?.(hasKey)
        message = detail || "API Key 无效，请重新配置"
        break
      }
      case 403:
        message = "需要管理员权限"
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
  } else {
    message = "网络连接失败，请稍后重试"
  }

  console.error("API 错误:", message, error)

  if (!suppressErrorToast && status !== 401) {
    messageService.error(message)
  }

  return Promise.reject(new ApiRequestError(message, {
    status,
    detail,
    isTimeout,
  }))
}

/** 响应拦截器 */
client.interceptors.response.use(
  (response: AxiosResponse) => {
    return response
  },
  handleApiError,
)

export { client }
