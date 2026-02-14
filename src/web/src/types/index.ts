/** 类型定义统一导出。 */

export * from "./tweet"
export * from "./task"
export * from "./scheduler"
export * from "./user"
export * from "./health"

/** API 错误响应。 */
export interface ApiError {
  /** 错误详情 */
  detail: string
}

/** 分页参数。 */
export interface PaginationParams {
  /** 页码（从 1 开始） */
  page?: number
  /** 每页数量 */
  page_size?: number
}
