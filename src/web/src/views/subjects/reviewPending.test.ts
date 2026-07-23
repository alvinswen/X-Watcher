import { describe, expect, it, vi } from "vitest"
import {
  markReviewPending,
  readReviewPending,
  reviewPendingKey,
  type ReviewPendingStorage,
} from "./reviewPending"

function memoryStorage(initial: Record<string, string> = {}): ReviewPendingStorage {
  const values = new Map(Object.entries(initial))
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  }
}

describe("reviewPending", () => {
  it("持久层版本匹配时返回待处理", () => {
    const subjectId = "subject-1"
    const storage = memoryStorage({
      [reviewPendingKey(subjectId)]: JSON.stringify({ pending: true, version: 3 }),
    })

    expect(readReviewPending(subjectId, 3, {}, storage)).toBe(true)
  })

  it("版本失配时自动清理会话与持久层记录", () => {
    const subjectId = "subject-2"
    const session = { [subjectId]: 2 }
    const removeItem = vi.fn()
    const storage: ReviewPendingStorage = {
      getItem: () => JSON.stringify({ pending: true, version: 2 }),
      setItem: vi.fn(),
      removeItem,
    }

    expect(readReviewPending(subjectId, 3, session, storage)).toBe(false)
    expect(session).not.toHaveProperty(subjectId)
    expect(removeItem).toHaveBeenCalledWith(reviewPendingKey(subjectId))
  })

  it("无存储记录时返回 false", () => {
    expect(readReviewPending("subject-3", 1, {}, memoryStorage())).toBe(false)
  })

  it("存储内容损坏时清理记录并回落到会话状态", () => {
    const subjectId = "subject-4"
    const removeItem = vi.fn()
    const storage: ReviewPendingStorage = {
      getItem: () => "{broken",
      setItem: vi.fn(),
      removeItem,
    }

    expect(readReviewPending(subjectId, 4, { [subjectId]: 4 }, storage)).toBe(true)
    expect(removeItem).toHaveBeenCalledWith(reviewPendingKey(subjectId))
  })

  it("存储不可用时仍保留当前会话状态", () => {
    const subjectId = "subject-5"
    const storage: ReviewPendingStorage = {
      getItem: () => {
        throw new Error("storage unavailable")
      },
      setItem: vi.fn(),
      removeItem: () => {
        throw new Error("storage unavailable")
      },
    }

    expect(readReviewPending(subjectId, 5, { [subjectId]: 5 }, storage)).toBe(true)
  })

  it("标记时同步写入会话与持久层，双源均可恢复", () => {
    const subjectId = "subject-6"
    const session: Record<string, number> = {}
    const storage = memoryStorage()

    expect(markReviewPending(subjectId, 6, session, storage)).toBe(true)
    expect(session[subjectId]).toBe(6)
    expect(readReviewPending(subjectId, 6, session, storage)).toBe(true)
  })
})
