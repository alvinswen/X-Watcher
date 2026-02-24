/** 数据同步类型定义。 */

/** 可同步的数据分类 */
export type SyncCategory = "config" | "content" | "topics"

/** 导入冲突解决策略 */
export type ConflictStrategy = "skip" | "overwrite" | "merge"

/** 导出请求参数 */
export interface ExportRequest {
  categories?: SyncCategory[]
  since?: string
  until?: string
  authors?: string[]
  instance_id?: string
}

/** 导出文件元数据 */
export interface ExportMetadata {
  format_version: string
  schema_version: number
  exported_at: string
  source_instance_id: string
  categories: string[]
  filters: {
    since: string | null
    until: string | null
    authors: string[] | null
  }
  counts: Record<string, number>
}

/** 单个表的导入统计 */
export interface ImportTableStats {
  inserted: number
  updated: number
  skipped: number
  errors: number
  total: number
}

/** 导入预览响应 */
export interface ImportPreviewResponse {
  metadata: ExportMetadata
  stats: Record<string, ImportTableStats>
  errors: string[]
  success: boolean
  dry_run: boolean
}

/** 导入执行响应 */
export interface ImportExecuteResponse {
  stats: Record<string, ImportTableStats>
  errors: string[]
  success: boolean
  dry_run: boolean
}
