/** 任务轮询服务单元测试。 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { taskPollingService } from "./polling"
import type { TaskStatusResponse } from "@/types"

describe("TaskPollingService", () => {
  afterEach(() => {
    taskPollingService.stopAll()
  })

  describe("启动轮询", () => {
    it("应该成功启动轮询并返回句柄", async () => {
      const mockFetchStatus = vi.fn().mockResolvedValue({
        task_id: "test-task",
        status: "pending" as const,
        result: null,
        error: null,
        created_at: new Date().toISOString(),
        started_at: null,
        completed_at: null,
        progress: { current: 0, total: 100, percentage: 0 },
        metadata: {},
      })

      const onStatusUpdate = vi.fn()
      const handle = taskPollingService.startPolling(
        "test-task",
        mockFetchStatus,
        onStatusUpdate,
      )

      expect(handle).toBeDefined()
      expect(typeof handle.cancel).toBe("function")

      // 等待初始轮询
      await new Promise(resolve => setTimeout(resolve, 10))

      expect(mockFetchStatus).toHaveBeenCalled()
      expect(onStatusUpdate).toHaveBeenCalled()

      handle.cancel()
    })

    it("应该立即执行一次轮询", async () => {
      const mockStatus: TaskStatusResponse = {
        task_id: "test-task",
        status: "pending",
        result: null,
        error: null,
        created_at: new Date().toISOString(),
        started_at: null,
        completed_at: null,
        progress: { current: 0, total: 100, percentage: 0 },
        metadata: {},
      }

      const mockFetchStatus = vi.fn().mockResolvedValue(mockStatus)
      const onStatusUpdate = vi.fn()

      taskPollingService.startPolling("test-task", mockFetchStatus, onStatusUpdate)

      // 等待微任务队列
      await new Promise(resolve => setTimeout(resolve, 10))

      expect(mockFetchStatus).toHaveBeenCalled()
      expect(onStatusUpdate).toHaveBeenCalledWith(mockStatus)

      taskPollingService.stopAll()
    })
  })

  describe("停止条件", () => {
    it("当任务完成时应该停止轮询", async () => {
      const completedStatus: TaskStatusResponse = {
        task_id: "test-task",
        status: "completed",
        result: { tweets_count: 10 },
        error: null,
        created_at: new Date().toISOString(),
        started_at: new Date().toISOString(),
        completed_at: new Date().toISOString(),
        progress: { current: 100, total: 100, percentage: 100 },
        metadata: {},
      }

      const mockFetchStatus = vi.fn().mockResolvedValue(completedStatus)
      const onStatusUpdate = vi.fn()
      const onComplete = vi.fn()

      taskPollingService.startPolling(
        "test-task",
        mockFetchStatus,
        onStatusUpdate,
        onComplete,
      )

      await new Promise(resolve => setTimeout(resolve, 100))

      expect(onComplete).toHaveBeenCalledWith(completedStatus)
    })

    it("当任务失败时应该停止轮询", async () => {
      const failedStatus: TaskStatusResponse = {
        task_id: "test-task",
        status: "failed",
        result: null,
        error: "Task failed",
        created_at: new Date().toISOString(),
        started_at: new Date().toISOString(),
        completed_at: new Date().toISOString(),
        progress: { current: 50, total: 100, percentage: 50 },
        metadata: {},
      }

      const mockFetchStatus = vi.fn().mockResolvedValue(failedStatus)
      const onStatusUpdate = vi.fn()
      const onComplete = vi.fn()

      taskPollingService.startPolling(
        "test-task",
        mockFetchStatus,
        onStatusUpdate,
        onComplete,
      )

      await new Promise(resolve => setTimeout(resolve, 100))

      expect(onComplete).toHaveBeenCalledWith(failedStatus)
    })

    it("当发生错误时应该停止轮询", async () => {
      const mockFetchStatus = vi.fn().mockRejectedValue(new Error("Network error"))
      const onStatusUpdate = vi.fn()
      const onError = vi.fn()

      taskPollingService.startPolling(
        "test-task",
        mockFetchStatus,
        onStatusUpdate,
        undefined,
        onError,
      )

      await new Promise(resolve => setTimeout(resolve, 100))

      expect(onError).toHaveBeenCalledWith(expect.any(Error))
    })
  })

  describe("取消轮询", () => {
    it("应该能够取消轮询", async () => {
      const mockStatus: TaskStatusResponse = {
        task_id: "test-task",
        status: "running",
        result: null,
        error: null,
        created_at: new Date().toISOString(),
        started_at: new Date().toISOString(),
        completed_at: null,
        progress: { current: 50, total: 100, percentage: 50 },
        metadata: {},
      }

      const mockFetchStatus = vi.fn().mockResolvedValue(mockStatus)
      const onStatusUpdate = vi.fn()

      const handle = taskPollingService.startPolling(
        "test-task",
        mockFetchStatus,
        onStatusUpdate,
      )

      // 等待初始轮询
      await new Promise(resolve => setTimeout(resolve, 50))

      const callCountBeforeCancel = mockFetchStatus.mock.calls.length

      // 取消轮询
      handle.cancel()

      // 等待一段时间，确保没有新的轮询
      await new Promise(resolve => setTimeout(resolve, 100))

      expect(mockFetchStatus.mock.calls.length).toBe(callCountBeforeCancel)
    })
  })

  describe("停止所有轮询", () => {
    it("应该能够停止所有正在进行的轮询", async () => {
      const mockStatus: TaskStatusResponse = {
        task_id: "test-task",
        status: "running",
        result: null,
        error: null,
        created_at: new Date().toISOString(),
        started_at: new Date().toISOString(),
        completed_at: null,
        progress: { current: 50, total: 100, percentage: 50 },
        metadata: {},
      }

      const mockFetchStatus = vi.fn().mockResolvedValue(mockStatus)
      const onStatusUpdate = vi.fn()

      // 启动多个轮询
      taskPollingService.startPolling("task1", mockFetchStatus, onStatusUpdate)
      taskPollingService.startPolling("task2", mockFetchStatus, onStatusUpdate)
      taskPollingService.startPolling("task3", mockFetchStatus, onStatusUpdate)

      await new Promise(resolve => setTimeout(resolve, 50))

      // 停止所有轮询
      taskPollingService.stopAll()

      // 等待一段时间，确保没有新的轮询
      await new Promise(resolve => setTimeout(resolve, 100))
    })
  })
})
