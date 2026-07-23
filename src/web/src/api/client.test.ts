import type { AxiosError, InternalAxiosRequestConfig } from "axios"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { messageService } from "@/services/message"
import type { ApiError } from "@/types"
import {
  ApiRequestError,
  handleApiError,
  setUnauthorizedHandler,
} from "./client"

function axiosError(options: {
  status?: number
  detail?: string
  code?: string
  message?: string
  suppressErrorToast?: boolean
  hasApiKey?: boolean
}): AxiosError<ApiError> {
  const apiKeyHeader = ["X", "API", "Key"].join("-")
  const config = {
    headers: options.hasApiKey ? { [apiKeyHeader]: "configured" } : {},
    suppressErrorToast: options.suppressErrorToast,
  } as InternalAxiosRequestConfig

  return {
    name: "AxiosError",
    message: options.message ?? "request failed",
    code: options.code,
    config,
    response: options.status === undefined
      ? undefined
      : {
          status: options.status,
          data: options.detail ? { detail: options.detail } : {},
        },
    isAxiosError: true,
    toJSON: () => ({}),
  } as AxiosError<ApiError>
}

describe("handleApiError", () => {
  const unauthorized = vi.fn()

  beforeEach(() => {
    vi.spyOn(messageService, "error").mockImplementation(() => undefined)
    vi.spyOn(console, "error").mockImplementation(() => undefined)
    unauthorized.mockReset()
    setUnauthorizedHandler(unauthorized)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("超时错误归一化并提示", async () => {
    await expect(handleApiError(axiosError({ code: "ECONNABORTED" }))).rejects.toMatchObject({
      message: "请求超时，请检查网络连接",
      isTimeout: true,
      status: null,
    } satisfies Partial<ApiRequestError>)
    expect(messageService.error).toHaveBeenCalledWith("请求超时，请检查网络连接")
  })

  it("401 不弹提示并触发未授权处理器", async () => {
    await expect(handleApiError(axiosError({
      status: 401,
      detail: "密钥失效",
      hasApiKey: true,
    }))).rejects.toMatchObject({
      message: "密钥失效",
      status: 401,
    } satisfies Partial<ApiRequestError>)
    expect(unauthorized).toHaveBeenCalledWith(true)
    expect(messageService.error).not.toHaveBeenCalled()
  })

  it("403 使用管理员权限提示", async () => {
    await expect(handleApiError(axiosError({ status: 403 }))).rejects.toMatchObject({
      message: "需要管理员权限",
      status: 403,
    } satisfies Partial<ApiRequestError>)
    expect(messageService.error).toHaveBeenCalledWith("需要管理员权限")
  })

  it("404 保留后端 detail", async () => {
    await expect(handleApiError(axiosError({
      status: 404,
      detail: "目标推文不存在",
    }))).rejects.toMatchObject({
      message: "目标推文不存在",
      detail: "目标推文不存在",
      status: 404,
    } satisfies Partial<ApiRequestError>)
    expect(messageService.error).toHaveBeenCalledWith("目标推文不存在")
  })

  it("500 使用服务器错误提示", async () => {
    await expect(handleApiError(axiosError({ status: 500 }))).rejects.toMatchObject({
      message: "服务器错误，请稍后重试",
      status: 500,
    } satisfies Partial<ApiRequestError>)
    expect(messageService.error).toHaveBeenCalledWith("服务器错误，请稍后重试")
  })

  it("无响应时提示网络连接失败", async () => {
    await expect(handleApiError(axiosError({}))).rejects.toMatchObject({
      message: "网络连接失败，请稍后重试",
      status: null,
    } satisfies Partial<ApiRequestError>)
    expect(messageService.error).toHaveBeenCalledWith("网络连接失败，请稍后重试")
  })

  it("静默标记抑制全局错误提示", async () => {
    await expect(handleApiError(axiosError({
      status: 500,
      suppressErrorToast: true,
    }))).rejects.toBeInstanceOf(ApiRequestError)
    expect(messageService.error).not.toHaveBeenCalled()
  })
})
