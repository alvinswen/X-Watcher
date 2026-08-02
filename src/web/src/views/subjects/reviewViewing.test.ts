import { describe, expect, it } from "vitest"
import type { SubjectReview } from "@/types"
import { reviewHasTrendOf } from "./reviewViewing"

function review(
  version: number,
  trend: SubjectReview["trend"],
): SubjectReview {
  return {
    subject_id: "sub_review",
    version,
    sections: [],
    trend,
    cited_tweet_ids: [],
    cited_tweets: [],
    missing_tweet_ids: [],
  }
}

describe("reviewHasTrendOf", () => {
  it("returns false for null review", () => {
    expect(reviewHasTrendOf(null)).toBe(false)
  })

  it("returns false for v1 even with trend content", () => {
    expect(reviewHasTrendOf(review(1, { emerging: ["新增"], fading: ["淡出"] }))).toBe(false)
  })

  it("returns false for v2 with empty trend", () => {
    expect(reviewHasTrendOf(review(2, { emerging: [], fading: [] }))).toBe(false)
  })

  it("returns true for v2 with emerging points", () => {
    expect(reviewHasTrendOf(review(2, { emerging: ["新增"], fading: [] }))).toBe(true)
  })

  it("returns true when only fading points exist", () => {
    expect(reviewHasTrendOf(review(3, { emerging: [], fading: ["淡出"] }))).toBe(true)
  })
})
