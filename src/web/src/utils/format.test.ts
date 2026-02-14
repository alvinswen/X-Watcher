import {
  formatRelativeTime,
  formatFullDateTime,
  formatLocalizedDateTime,
  formatDuration,
} from "./format"

describe("formatRelativeTime", () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-02-14T12:00:00Z"))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it("null 返回 '未知'", () => {
    expect(formatRelativeTime(null)).toBe("未知")
  })

  it("30 秒前 → '刚刚'", () => {
    const date = new Date(Date.now() - 30 * 1000).toISOString()
    expect(formatRelativeTime(date)).toBe("刚刚")
  })

  it("5 分钟前 → '5分钟前'", () => {
    const date = new Date(Date.now() - 5 * 60 * 1000).toISOString()
    expect(formatRelativeTime(date)).toBe("5分钟前")
  })

  it("3 小时前 → '3小时前'", () => {
    const date = new Date(Date.now() - 3 * 3600 * 1000).toISOString()
    expect(formatRelativeTime(date)).toBe("3小时前")
  })

  it("2 天前 → '2天前'", () => {
    const date = new Date(Date.now() - 2 * 86400 * 1000).toISOString()
    expect(formatRelativeTime(date)).toBe("2天前")
  })

  it("10 天前 → 返回本地化日期格式", () => {
    const date = new Date(Date.now() - 10 * 86400 * 1000).toISOString()
    const result = formatRelativeTime(date)
    // 本地化日期格式可能是 "2026/2/4" 或 "2/4/2026" 等，验证包含关键信息
    expect(result).toMatch(/2026|2\/4/)
  })
})

describe("formatFullDateTime", () => {
  it("null 返回 '-'", () => {
    expect(formatFullDateTime(null)).toBe("-")
  })

  it("正常日期字符串 → 包含年月日时分秒", () => {
    const result = formatFullDateTime("2026-02-14T12:30:45Z")
    // 验证返回结果包含年、月、日、时、分、秒的数字部分
    expect(result).toMatch(/2026/)
    expect(result).toMatch(/02|2/)
    expect(result).toMatch(/14/)
    // 时分秒取决于本地时区，但应包含数字
    expect(result.length).toBeGreaterThan(10)
  })
})

describe("formatLocalizedDateTime", () => {
  it("null 返回 '-'", () => {
    expect(formatLocalizedDateTime(null)).toBe("-")
  })

  it("正常日期 → 非空字符串", () => {
    const result = formatLocalizedDateTime("2026-02-14T12:30:45Z")
    expect(result).toBeTruthy()
    expect(result.length).toBeGreaterThan(0)
  })
})

describe("formatDuration", () => {
  it("null → '-'", () => {
    expect(formatDuration(null)).toBe("-")
  })

  it("0 → '0 秒'", () => {
    expect(formatDuration(0)).toBe("0 秒")
  })

  it("30 → '30 秒'", () => {
    expect(formatDuration(30)).toBe("30 秒")
  })

  it("59 → '59 秒'", () => {
    expect(formatDuration(59)).toBe("59 秒")
  })

  it("60 → '1 分钟'", () => {
    expect(formatDuration(60)).toBe("1 分钟")
  })

  it("3600 → '1 小时'", () => {
    expect(formatDuration(3600)).toBe("1 小时")
  })

  it("86400 → '1 天'", () => {
    expect(formatDuration(86400)).toBe("1 天")
  })

  it("90061 → '1 天 1 小时 1 分钟'", () => {
    expect(formatDuration(90061)).toBe("1 天 1 小时 1 分钟")
  })

  it("7200 → '2 小时'", () => {
    expect(formatDuration(7200)).toBe("2 小时")
  })

  it("9000 → '2 小时 30 分钟'", () => {
    expect(formatDuration(9000)).toBe("2 小时 30 分钟")
  })
})
