/** 通用时间格式化工具函数 */

/**
 * 相对时间（如"3分钟前"、"2天前"）
 * @param dateStr ISO 日期字符串，null 返回 "未知"
 */
export function formatRelativeTime(dateStr: string | null): string {
  if (!dateStr) return "未知"
  const date = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  const minutes = Math.floor(diff / 60000)
  const hours = Math.floor(diff / 3600000)
  const days = Math.floor(diff / 86400000)

  if (minutes < 1) return "刚刚"
  if (minutes < 60) return `${minutes}分钟前`
  if (hours < 24) return `${hours}小时前`
  if (days < 7) return `${days}天前`
  return date.toLocaleDateString("zh-CN")
}

/**
 * 完整日期时间格式 "YYYY-MM-DD HH:mm:ss"
 * @param dateStr ISO 日期字符串，null 返回 "-"
 */
export function formatFullDateTime(dateStr: string | null): string {
  if (!dateStr) return "-"
  const date = new Date(dateStr)
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  })
}

/**
 * 本地化日期时间（zh-CN locale）
 * @param dateStr ISO 日期字符串，null 返回 "-"
 */
export function formatLocalizedDateTime(dateStr: string | null): string {
  if (!dateStr) return "-"
  const date = new Date(dateStr)
  return date.toLocaleString("zh-CN")
}

/**
 * 秒数转可读时间描述（如"2 小时 30 分钟"）
 * @param seconds 秒数，null 返回 "-"
 */
export function formatDuration(seconds: number | null): string {
  if (seconds === null || seconds === undefined) return "-"
  if (seconds < 60) return `${seconds} 秒`

  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)

  const parts: string[] = []
  if (days > 0) parts.push(`${days} 天`)
  if (hours > 0) parts.push(`${hours} 小时`)
  if (minutes > 0) parts.push(`${minutes} 分钟`)

  return parts.join(" ") || "0 秒"
}
