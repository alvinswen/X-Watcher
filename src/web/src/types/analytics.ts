/** 统计分析类型定义。 */

/** 时间范围 */
export interface TimeRange {
  start: string
  end: string
}

/** 单个时段的发文计数 */
export interface FrequencySlot {
  slot: string
  count: number
}

/** 发文频次分析响应 */
export interface PostingFrequencyResponse {
  topic_id: number
  topic_name: string
  slot_minutes: number
  slots: number
  tz_offset: number
  time_range: TimeRange
  distribution: FrequencySlot[]
  total_tweets: number
}
