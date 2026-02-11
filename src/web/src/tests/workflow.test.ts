/** 抓取工作流端到端测试。 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { taskPollingService } from "@/services/polling"
import { tasksApi } from "@/api"
import type { TaskStatusResponse } from "@/types"

// Mock API
vi.mock("@/api", () => ({
  tasksApi: {
    triggerScraping: vi.fn(),
    getStatus: vi.fn(),
  },
}))

describe("抓取工作流端到端测试", () => {
  afterEach(() => {
    taskPollingService.stopAll()
  })

  describe("完整工作流", () => {
    it("应该成功执行抓取工作流：触发 -> 轮询 -> 完成", async () => {
      // 1. 触发抓取任务
      const triggerResponse = {
        task_id: "test-task-123",
        status: "pending",
      }
      vi.mocked(tasksApi.triggerScraping).mockResolvedValue(triggerResponse)

      const triggerResult = await tasksApi.triggerScraping({
        usernames: "",
        limit: 100,
      })

      expect(triggerResult).toEqual(triggerResponse)
      expect(tasksApi.triggerScraping).toHaveBeenCalledWith({
        usernames: "",
        limit: 100,
      })

      // 2. 模拟任务完成
      const completedStatus: TaskStatusResponse = {
        task_id: "test-task-123",
        status: "completed",
        result: {
          tweets_count: 50,
          deduplication_count: 5,
          summary_count: 45,
        },
        error: null,
        created_at: new Date().toISOString(),
        started_at: new Date().toISOString(),
        completed_at: new Date().toISOString(),
        progress: { current: 100, total: 100, percentage: 100 },
        metadata: {},
      }

      vi.mocked(tasksApi.getStatus).mockResolvedValue(completedStatus)

      // 3. 启动轮询
      const statusUpdates: TaskStatusResponse[] = []
      let completedStatusResult: TaskStatusResponse | null = null

      taskPollingService.startPolling(
        "test-task-123",
        () => tasksApi.getStatus("test-task-123"),
        (status) => {
          statusUpdates.push(status)
        },
        (status) => {
          completedStatusResult = status
        },
      )

      // 4. 等待轮询完成
      await new Promise(resolve => setTimeout(resolve, 200))

      // 5. 验证结果
      expect(completedStatusResult).not.toBeNull()
      expect(completedStatusResult!.status).toBe("completed")
      expect(completedStatusResult!.result).toEqual({
        tweets_count: 50,
        deduplication_count: 5,
        summary_count: 45,
      })

      expect(statusUpdates.length).toBeGreaterThan(0)
    })
  })

  describe("任务失败场景", () => {
    it("应该在任务失败时停止轮询并显示错误", async () => {
      // 1. 触发任务
      vi.mocked(tasksApi.triggerScraping).mockResolvedValue({
        task_id: "failed-task",
        status: "pending",
      })

      await tasksApi.triggerScraping({ usernames: "", limit: 100 })

      // 2. 模拟任务失败
      const failedStatus: TaskStatusResponse = {
        task_id: "failed-task",
        status: "failed",
        result: null,
        error: "Scraping failed: Unable to connect to Twitter API",
        created_at: new Date().toISOString(),
        started_at: new Date().toISOString(),
        completed_at: new Date().toISOString(),
        progress: { current: 10, total: 100, percentage: 10 },
        metadata: { stage: "scraping" },
      }

      vi.mocked(tasksApi.getStatus).mockResolvedValue(failedStatus)

      // 3. 启动轮询
      let completedStatus: TaskStatusResponse | null = null

      taskPollingService.startPolling(
        "failed-task",
        () => tasksApi.getStatus("failed-task"),
        () => {},
        (status) => {
          completedStatus = status
        },
      )

      // 4. 执行轮询
      await new Promise(resolve => setTimeout(resolve, 200))

      // 5. 验证失败状态
      expect(completedStatus).not.toBeNull()
      expect(completedStatus!.status).toBe("failed")
      expect(completedStatus!.error).toBe("Scraping failed: Unable to connect to Twitter API")
    })
  })

  describe("网络错误场景", () => {
    it("应该处理轮询过程中的网络错误", async () => {
      // 1. 触发任务
      vi.mocked(tasksApi.triggerScraping).mockResolvedValue({
        task_id: "network-error-task",
        status: "pending",
      })

      // 2. 模拟网络错误
      vi.mocked(tasksApi.getStatus).mockRejectedValue(
        new Error("Network Error: Service unavailable")
      )

      // 3. 启动轮询
      let errorOccurred: Error | null = null

      taskPollingService.startPolling(
        "network-error-task",
        () => tasksApi.getStatus("network-error-task"),
        () => {},
        undefined,
        (error) => {
          errorOccurred = error
        },
      )

      // 4. 执行轮询
      await new Promise(resolve => setTimeout(resolve, 200))

      // 5. 验证错误被捕获
      expect(errorOccurred).not.toBeNull()
      expect(errorOccurred!.message).toContain("Network Error")
    })
  })

  describe("轮询取消", () => {
    it("应该能够取消正在进行的轮询", async () => {
      // 1. 触发任务
      vi.mocked(tasksApi.triggerScraping).mockResolvedValue({
        task_id: "cancel-task",
        status: "pending",
      })

      // 2. 模拟长时间运行的任务
      const runningStatus: TaskStatusResponse = {
        task_id: "cancel-task",
        status: "running",
        result: null,
        error: null,
        created_at: new Date().toISOString(),
        started_at: new Date().toISOString(),
        completed_at: null,
        progress: { current: 50, total: 100, percentage: 50 },
        metadata: {},
      }

      vi.mocked(tasksApi.getStatus).mockResolvedValue(runningStatus)

      // 3. 启动轮询
      const handle = taskPollingService.startPolling(
        "cancel-task",
        () => tasksApi.getStatus("cancel-task"),
        () => {},
      )

      // 4. 执行一次轮询
      await new Promise(resolve => setTimeout(resolve, 50))
      expect(tasksApi.getStatus).toHaveBeenCalled()

      const callCountBeforeCancel = tasksApi.getStatus.mock.calls.length

      // 5. 取消轮询
      handle.cancel()

      // 6. 等待一段时间，验证不再执行轮询
      await new Promise(resolve => setTimeout(resolve, 100))

      // 应该只执行了一次
      expect(tasksApi.getStatus.mock.calls.length).toBe(callCountBeforeCancel)
    })
  })

  describe("进度跟踪", () => {
    it("应该正确跟踪和更新任务进度", async () => {
      // 1. 触发任务
      vi.mocked(tasksApi.triggerScraping).mockResolvedValue({
        task_id: "progress-task",
        status: "pending",
      })

      // 2. 模拟进度变化（从 0% 到 100%）
      let progressIndex = 0
      const progressSequence: TaskStatusResponse[] = [
        {
          task_id: "progress-task",
          status: "running",
          result: null,
          error: null,
          created_at: new Date().toISOString(),
          started_at: new Date().toISOString(),
          completed_at: null,
          progress: { current: 0, total: 100, percentage: 0 },
          metadata: { stage: "scraping" },
        },
        {
          task_id: "progress-task",
          status: "running",
          result: null,
          error: null,
          created_at: new Date().toISOString(),
          started_at: new Date().toISOString(),
          completed_at: null,
          progress: { current: 60, total: 100, percentage: 60 },
          metadata: { stage: "deduplication" },
        },
        {
          task_id: "progress-task",
          status: "completed",
          result: { tweets_count: 60 },
          error: null,
          created_at: new Date().toISOString(),
          started_at: new Date().toISOString(),
          completed_at: new Date().toISOString(),
          progress: { current: 100, total: 100, percentage: 100 },
          metadata: {},
        },
      ]

      vi.mocked(tasksApi.getStatus).mockImplementation(async () => {
        return progressSequence[progressIndex++]
      })

      // 3. 收集所有状态更新
      const statusUpdates: TaskStatusResponse[] = []

      taskPollingService.startPolling(
        "progress-task",
        () => tasksApi.getStatus("progress-task"),
        (status) => {
          statusUpdates.push(status)
        },
      )

      // 4. 等待完成
      await new Promise(resolve => setTimeout(resolve, 500))

      // 5. 验证至少收到了初始状态和完成状态
      expect(statusUpdates.length).toBeGreaterThan(0)

      // 验证至少有一个完成状态
      const completedStates = statusUpdates.filter(s => s.status === "completed")
      expect(completedStates.length).toBeGreaterThan(0)
    })
  })
})
