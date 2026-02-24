/** 数据同步 API 客户端。 */

import { client } from "./client"
import type {
  ExportRequest,
  ImportPreviewResponse,
  ImportExecuteResponse,
  ConflictStrategy,
  SyncCategory,
} from "@/types/sync"

const PREFIX = "/admin/sync"

export const syncApi = {
  /** 导出数据（返回 blob 和文件名） */
  async exportData(
    params: ExportRequest,
  ): Promise<{ blob: Blob; filename: string }> {
    const response = await client.post(`${PREFIX}/export`, params, {
      responseType: "blob",
      timeout: 120000,
    })

    // 从 Content-Disposition 提取文件名
    const disposition = response.headers["content-disposition"] || ""
    const match = disposition.match(/filename="?([^";\s]+)"?/)
    const filename = match ? match[1] : `x-watcher-export.json`

    return { blob: response.data as Blob, filename }
  },

  /** 预览导入（dry-run） */
  async previewImport(
    file: File,
    categories?: SyncCategory[],
    strategy?: ConflictStrategy,
  ): Promise<ImportPreviewResponse> {
    const formData = new FormData()
    formData.append("file", file)
    if (categories?.length) {
      formData.append("categories", categories.join(","))
    }
    if (strategy) {
      formData.append("strategy", strategy)
    }

    const response = await client.post<ImportPreviewResponse>(
      `${PREFIX}/import/preview`,
      formData,
      {
        headers: { "Content-Type": undefined as unknown as string },
        timeout: 120000,
      },
    )
    return response.data
  },

  /** 执行实际导入 */
  async executeImport(
    file: File,
    categories?: SyncCategory[],
    strategy?: ConflictStrategy,
  ): Promise<ImportExecuteResponse> {
    const formData = new FormData()
    formData.append("file", file)
    if (categories?.length) {
      formData.append("categories", categories.join(","))
    }
    if (strategy) {
      formData.append("strategy", strategy)
    }

    const response = await client.post<ImportExecuteResponse>(
      `${PREFIX}/import/execute`,
      formData,
      {
        headers: { "Content-Type": undefined as unknown as string },
        timeout: 120000,
      },
    )
    return response.data
  },
}
