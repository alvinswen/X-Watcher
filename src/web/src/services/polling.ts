/** 任务状态轮询服务。 */

import type { TaskStatusResponse } from "@/types"

/** 轮询间隔（毫秒） */
const POLLING_INTERVAL = 2000

/** 状态更新回调类型 */
export type StatusUpdateCallback = (status: TaskStatusResponse) => void

/** 轮询句柄 */
export interface PollingHandle {
  /** 取消轮询 */
  cancel: () => void
}

/** 任务轮询服务。 */
export class TaskPollingService {
  private timers: Map<string, ReturnType<typeof setInterval>> = new Map()
  private aborted: Map<string, boolean> = new Map()

  /**
   * 启动任务状态轮询。
   *
   * @param taskId 任务 ID
   * @param fetchStatus 获取任务状态的函数
   * @param onStatusUpdate 状态更新回调
   * @param onComplete 任务完成回调
   * @param onError 任务错误回调
   * @returns 轮询句柄
   */
  startPolling(
    taskId: string,
    fetchStatus: () => Promise<TaskStatusResponse>,
    onStatusUpdate: StatusUpdateCallback,
    onComplete?: (status: TaskStatusResponse) => void,
    onError?: (error: Error) => void,
  ): PollingHandle {
    // 标记任务未中止
    this.aborted.set(taskId, false)

    // 轮询函数
    const poll = async () => {
      // 检查是否已中止
      if (this.aborted.get(taskId)) {
        return
      }

      try {
        const status = await fetchStatus()

        // 更新状态
        onStatusUpdate(status)

        // 检查任务是否完成或失败
        if (status.status === "completed" || status.status === "failed") {
          this.stopPolling(taskId)
          if (onComplete) {
            onComplete(status)
          }
        }
      } catch (error) {
        this.stopPolling(taskId)
        if (onError) {
          onError(error as Error)
        }
      }
    }

    // 立即执行一次
    poll().catch(() => {
      // 首次轮询错误已被 onError 处理
    })

    // 设置定时器
    const timerId = setInterval(poll, POLLING_INTERVAL)
    this.timers.set(taskId, timerId)

    // 返回句柄
    return {
      cancel: () => this.stopPolling(taskId),
    }
  }

  /**
   * 停止任务状态轮询。
   *
   * @param taskId 任务 ID
   */
  stopPolling(taskId: string): void {
    // 标记为中止
    this.aborted.set(taskId, true)

    // 清除定时器
    const timerId = this.timers.get(taskId)
    if (timerId) {
      clearInterval(timerId)
      this.timers.delete(taskId)
    }
  }

  /**
   * 停止所有轮询。
   */
  stopAll(): void {
    for (const taskId of this.timers.keys()) {
      this.stopPolling(taskId)
    }
  }
}

/** 全局轮询服务实例 */
export const taskPollingService = new TaskPollingService()
