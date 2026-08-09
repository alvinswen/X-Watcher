import { describe, expect, it } from "vitest"
import {
  displaySummary,
  isCjkDominant,
  segmentHighlight,
  splitSearchTerms,
  stripRedundantPrefix,
  termHits,
} from "./tweetReading"

describe("stripRedundantPrefix", () => {
  it.each([
    ["@karpathy 引用 @sama：模型评测应该更看重真实任务", "karpathy", "模型评测应该更看重真实任务"],
    ["@karpathy 转发：这是一条转发说明", "karpathy", "这是一条转发说明"],
    ["@karpathy，今天发布了新模型", "karpathy", "今天发布了新模型"],
    ["@sama 说得对，评测确实该改", "karpathy", "@sama 说得对，评测确实该改"],
    ["@karpathy 引用 @sama：", "karpathy", "@karpathy 引用 @sama："],
    ["@elonmusk 回复 @jack: lowercase colon test", "elonmusk", "lowercase colon test"],
    ["", "karpathy", ""],
  ])("maps %s to the frozen oracle result", (summary, author, expected) => {
    expect(stripRedundantPrefix(summary, author)).toBe(expected)
  })
})

describe("isCjkDominant", () => {
  it("includes the exact 0.15 threshold", () => {
    expect(isCjkDominant("汉汉汉xxxxxxxxxxxxxxxxx")).toBe(true)
  })

  it("rejects English, empty, and null text", () => {
    expect(isCjkDominant("plain English text")).toBe(false)
    expect(isCjkDominant("")).toBe(false)
    expect(isCjkDominant(null)).toBe(false)
  })
})

describe("search helpers", () => {
  it("splits on arbitrary whitespace and matches case-insensitively", () => {
    expect(splitSearchTerms("  Agent\n预言  ")).toEqual(["Agent", "预言"])
    expect(termHits("An AGENT roadmap", "agent")).toBe(true)
    expect(termHits(null, "agent")).toBe(false)
  })

  it("merges overlapping highlight ranges", () => {
    expect(segmentHighlight("abc", ["ab", "bc"])).toEqual([{ text: "abc", hit: true }])
  })

  it("preserves case, treats wildcard characters literally, and handles no hits", () => {
    expect(segmentHighlight("Agent %_", ["agent", "%_"])).toEqual([
      { text: "Agent", hit: true },
      { text: " ", hit: false },
      { text: "%_", hit: true },
    ])
    expect(segmentHighlight("plain", [])).toEqual([{ text: "plain", hit: false }])
    expect(segmentHighlight("", ["x"])).toEqual([])
  })
})

describe("displaySummary", () => {
  it("keeps the original summary when stripping would erase an existing hit", () => {
    const summary = "@a 引用 @b：找 keyword 的话"
    expect(displaySummary(summary, "a", ["@b"])).toBe(summary)
  })

  it("keeps the stripped summary when the term never matched the summary", () => {
    expect(displaySummary("@a 引用 @b：找 keyword 的话", "a", ["translation-only"])).toBe("找 keyword 的话")
  })
})
