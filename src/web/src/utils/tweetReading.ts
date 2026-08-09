/** 推文阅读模式显示层工具（CHG-060）。
 *  全部函数为纯函数、只作用于屏幕显示，不回写任何数据。
 *  注：JS \w 仅 ASCII；X handle 合法字符恰为 [A-Za-z0-9_]，与 Python 版等价。 */

const PREFIX_WITH_TARGET = /^@\w+\s*(?:引用|回复|转推|转发)\s*@\w+\s*[:：]\s*/
const PREFIX_BARE = /^@\w+\s*(?:引用|回复|转推|转发)\s*[:：]\s*/
const LEADING_PUNCT = /^[，,：:、；;\s]+/
const CJK = /[一-鿿]/g

/** 剥掉与作者行重复的摘要开头；开头是别人的 @handle 则保留；剥空回退原摘要。 */
export function stripRedundantPrefix(summary: string, author: string): string {
  if (!summary) return ""
  let stripped = summary.replace(PREFIX_WITH_TARGET, "")
  if (stripped === summary) stripped = summary.replace(PREFIX_BARE, "")
  const selfTag = `@${author}`
  if (author && stripped.startsWith(selfTag)) {
    stripped = stripped.slice(selfTag.length).trimStart().replace(LEADING_PUNCT, "")
  }
  return stripped.trim() || summary
}

/** 「原文即中文」：中文汉字数 ÷ 总字符数 ≥ 0.15。 */
export function isCjkDominant(text: string | null, threshold = 0.15): boolean {
  if (!text) return false
  return (text.match(CJK) ?? []).length / text.length >= threshold
}

/** 复刻后端 q.split()：任意空白拆词。 */
export function splitSearchTerms(query: string): string[] {
  return query.trim().split(/\s+/).filter(Boolean)
}

/** 单词命中：不区分大小写的字面子串包含。 */
export function termHits(haystack: string | null, term: string): boolean {
  if (!haystack || !term) return false
  return haystack.toLowerCase().includes(term.toLowerCase())
}

export interface HighlightSegment {
  text: string
  hit: boolean
}

/** 收集全部词的全部命中区间，合并重叠/相接区间后输出安全的文本分段。 */
export function segmentHighlight(text: string, terms: string[]): HighlightSegment[] {
  if (!text) return []
  const ranges: Array<[number, number]> = []
  const lower = text.toLowerCase()
  for (const term of terms) {
    if (!term) continue
    const target = term.toLowerCase()
    let from = 0
    for (let index = lower.indexOf(target, from); index !== -1; index = lower.indexOf(target, from)) {
      ranges.push([index, index + target.length])
      from = index + 1
    }
  }
  if (!ranges.length) return [{ text, hit: false }]
  ranges.sort((left, right) => left[0] - right[0])
  const merged: Array<[number, number]> = [ranges[0]!]
  for (const [start, end] of ranges.slice(1)) {
    const last = merged[merged.length - 1]!
    if (start <= last[1]) last[1] = Math.max(last[1], end)
    else merged.push([start, end])
  }
  const segments: HighlightSegment[] = []
  let position = 0
  for (const [start, end] of merged) {
    if (start > position) segments.push({ text: text.slice(position, start), hit: false })
    segments.push({ text: text.slice(start, end), hit: true })
    position = end
  }
  if (position < text.length) segments.push({ text: text.slice(position), hit: false })
  return segments
}

/** 阅读态 L1 显示摘要；剥离不得丢失摘要里原本存在的搜索命中。 */
export function displaySummary(summary: string, author: string, terms: string[]): string {
  const stripped = stripRedundantPrefix(summary, author)
  if (terms.length) {
    const lostMatch = terms.some((term) => termHits(summary, term) && !termHits(stripped, term))
    if (lostMatch) return summary
  }
  return stripped
}
