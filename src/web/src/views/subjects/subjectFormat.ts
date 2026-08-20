export function formatDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date)
}

export function formatAbsoluteDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date)
}

export function formatDatePart(date: Date): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
  }).format(date).replace(/\//g, "-")
}

export function formatTimePart(date: Date): string {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date)
}

function sameLocalDate(start: Date, end: Date): boolean {
  return start.getFullYear() === end.getFullYear()
    && start.getMonth() === end.getMonth()
    && start.getDate() === end.getDate()
}

export function formatIntervalLabel(startValue: string, endValue: string): string {
  const start = new Date(startValue)
  const end = new Date(endValue)
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
    return `${startValue}~${endValue}`
  }
  if (sameLocalDate(start, end)) {
    return `${formatDatePart(start)} ${formatTimePart(start)}~${formatTimePart(end)}`
  }
  return `${formatDatePart(start)} ${formatTimePart(start)} ~ ${formatDatePart(end)} ${formatTimePart(end)}`
}

/**
 * CHG-064 渲染契约：正文允许用空行（\n\n）分段，网页端必须按段展示。
 * - 综述 SubjectReviewSection.body 与摘要 SubjectDigest.digest_text 共用本函数（两页签单一口径）
 * - CRLF 防御归一（现存数据 \r = 0，防未来生成侧环境差异）
 * - 连续多空行视同一个分隔；空白段过滤不渲染
 * - 段内孤立单换行保留在段文本内（渲染时经 HTML 空白折叠“照常显示”）
 */
export function splitParagraphs(text: string): string[] {
  return text
    .replace(/\r\n/g, "\n")
    .split(/\n{2,}/)
    .map((paragraph) => paragraph.trim())
    .filter((paragraph) => paragraph.length > 0)
}
