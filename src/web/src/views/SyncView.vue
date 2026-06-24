<script setup lang="ts">
import { ref, computed } from "vue"
import { ElMessage, ElMessageBox } from "element-plus"
import { syncApi } from "@/api/sync"
import type {
  SyncCategory,
  ConflictStrategy,
  ExportMetadata,
  ImportPreviewResponse,
  ImportExecuteResponse,
  ImportTableStats,
} from "@/types/sync"

// ── 导出状态 ──

const syncCategoryOptions: Array<{ value: SyncCategory; label: string }> = [
  { value: "config", label: "配置数据" },
  { value: "content", label: "内容数据" },
]
const supportedCategoryValues = new Set<string>(
  syncCategoryOptions.map((option) => option.value),
)

function isSupportedSyncCategory(category: string): category is SyncCategory {
  return supportedCategoryValues.has(category)
}

const exportCategories = ref<SyncCategory[]>(["config", "content"])
const exportSince = ref("")
const exportUntil = ref("")
const exportAuthors = ref("")
const exportInstanceId = ref("")
const exporting = ref(false)
const exportResult = ref<Record<string, number> | null>(null)

const showContentFilters = computed(() => exportCategories.value.includes("content"))

async function handleExport() {
  if (!exportCategories.value.length) {
    ElMessage.warning("请至少选择一个导出分类")
    return
  }
  exporting.value = true
  exportResult.value = null
  try {
    const authors = exportAuthors.value
      .split(",")
      .map((a) => a.trim())
      .filter(Boolean)

    const { blob, filename } = await syncApi.exportData({
      categories: exportCategories.value,
      since: exportSince.value || undefined,
      until: exportUntil.value || undefined,
      authors: authors.length ? authors : undefined,
      instance_id: exportInstanceId.value || undefined,
    })

    // 解析 blob 获取统计信息
    try {
      const text = await blob.text()
      const data = JSON.parse(text)
      if (data.metadata?.counts) {
        exportResult.value = data.metadata.counts
      }
    } catch {
      // 解析失败不影响下载
    }

    // 触发浏览器下载
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)

    ElMessage.success("导出完成，文件已开始下载")
  } catch {
    // client 拦截器已处理错误提示
  } finally {
    exporting.value = false
  }
}

// ── 导入状态 ──

const importFile = ref<File | null>(null)
const importCategories = ref<SyncCategory[]>([])
const importStrategy = ref<ConflictStrategy>("skip")
const importing = ref(false)
const previewing = ref(false)
const previewResult = ref<ImportPreviewResponse | null>(null)
const importResult = ref<ImportExecuteResponse | null>(null)
const fileMetadata = ref<ExportMetadata | null>(null)

const importableCategories = computed(() =>
  fileMetadata.value?.categories.filter(isSupportedSyncCategory) ?? [],
)

/** 文件选择变更 */
function handleFileChange(uploadFile: { raw: File }) {
  const file = uploadFile.raw
  importFile.value = file
  previewResult.value = null
  importResult.value = null
  fileMetadata.value = null
  importCategories.value = []

  // 客户端解析 JSON 获取元数据
  const reader = new FileReader()
  reader.onload = (e) => {
    try {
      const data = JSON.parse(e.target?.result as string)
      if (data.metadata) {
        fileMetadata.value = data.metadata
        // 自动选中文件中包含的分类
        if (data.metadata.categories?.length) {
          importCategories.value = data.metadata.categories.filter(
            isSupportedSyncCategory,
          ) as SyncCategory[]
        }
      }
    } catch {
      ElMessage.error("无法解析文件，请确认为有效的导出 JSON 文件")
      importFile.value = null
    }
  }
  reader.readAsText(file)
}

/** 移除文件 */
function handleFileRemove() {
  importFile.value = null
  fileMetadata.value = null
  previewResult.value = null
  importResult.value = null
  importCategories.value = []
}

/** 预览导入 */
async function handlePreview() {
  if (!importFile.value) {
    ElMessage.warning("请先选择文件")
    return
  }
  if (!importCategories.value.length) {
    ElMessage.warning("请至少选择一个导入分类")
    return
  }
  previewing.value = true
  previewResult.value = null
  importResult.value = null
  try {
    previewResult.value = await syncApi.previewImport(
      importFile.value,
      importCategories.value,
      importStrategy.value,
    )
    ElMessage.success("预览完成")
  } catch {
    // client 拦截器已处理
  } finally {
    previewing.value = false
  }
}

/** 执行导入 */
async function handleImport() {
  if (!importFile.value) return

  try {
    await ElMessageBox.confirm(
      "确定要执行导入吗？此操作将修改数据库。",
      "确认导入",
      { type: "warning" },
    )
  } catch {
    return
  }

  importing.value = true
  importResult.value = null
  try {
    importResult.value = await syncApi.executeImport(
      importFile.value,
      importCategories.value,
      importStrategy.value,
    )
    if (importResult.value.success) {
      ElMessage.success("导入完成")
    } else {
      ElMessage.warning("导入完成，但存在错误")
    }
  } catch {
    // client 拦截器已处理
  } finally {
    importing.value = false
  }
}

/** 格式化统计表格数据 */
function formatStatsTable(stats: Record<string, ImportTableStats>) {
  return Object.entries(stats).map(([table, s]) => ({
    table,
    ...s,
  }))
}

/** 格式化日期 */
function formatDate(value: string | null | undefined): string {
  if (!value) return "-"
  try {
    return new Date(value).toLocaleString("zh-CN")
  } catch {
    return value
  }
}

/** 分类显示名 */
const categoryLabels: Record<SyncCategory, string> = Object.fromEntries(
  syncCategoryOptions.map((option) => [option.value, option.label]),
) as Record<SyncCategory, string>

/** 策略显示名 */
const strategyLabels: Record<ConflictStrategy, string> = {
  skip: "跳过 — 已存在则不覆盖",
  overwrite: "覆盖 — 已存在则替换",
  merge: "合并 — 合并已有数据",
}
</script>

<template>
  <div class="sync-view">
    <el-row :gutter="20">
      <!-- 导出卡片 -->
      <el-col :span="12">
        <el-card shadow="never">
          <template #header>
            <span class="card-title">数据导出</span>
          </template>

          <el-form label-position="top">
            <!-- 分类选择 -->
            <el-form-item label="导出分类">
              <el-checkbox-group v-model="exportCategories">
                <el-checkbox
                  v-for="option in syncCategoryOptions"
                  :key="option.value"
                  :value="option.value"
                >
                  {{ option.label }}
                </el-checkbox>
              </el-checkbox-group>
            </el-form-item>

            <!-- content 过滤条件 -->
            <template v-if="showContentFilters">
              <el-form-item label="时间范围（可选）">
                <el-row :gutter="12" style="width: 100%">
                  <el-col :span="12">
                    <el-date-picker
                      v-model="exportSince"
                      type="datetime"
                      placeholder="开始时间"
                      value-format="YYYY-MM-DDTHH:mm:ss"
                      style="width: 100%"
                    />
                  </el-col>
                  <el-col :span="12">
                    <el-date-picker
                      v-model="exportUntil"
                      type="datetime"
                      placeholder="结束时间"
                      value-format="YYYY-MM-DDTHH:mm:ss"
                      style="width: 100%"
                    />
                  </el-col>
                </el-row>
              </el-form-item>

              <el-form-item label="作者过滤（可选，逗号分隔）">
                <el-input
                  v-model="exportAuthors"
                  placeholder="如: user1, user2"
                />
              </el-form-item>
            </template>

            <!-- 实例标识 -->
            <el-form-item label="实例标识（可选）">
              <el-input
                v-model="exportInstanceId"
                placeholder="默认: web-export"
              />
            </el-form-item>

            <el-form-item>
              <el-button
                type="primary"
                :loading="exporting"
                @click="handleExport"
              >
                导出
              </el-button>
            </el-form-item>
          </el-form>

          <!-- 导出结果统计 -->
          <div v-if="exportResult" class="result-section">
            <el-divider content-position="left">导出统计</el-divider>
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item
                v-for="(count, table) in exportResult"
                :key="table"
                :label="String(table)"
              >
                {{ count }}
              </el-descriptions-item>
            </el-descriptions>
          </div>
        </el-card>
      </el-col>

      <!-- 导入卡片 -->
      <el-col :span="12">
        <el-card shadow="never">
          <template #header>
            <span class="card-title">数据导入</span>
          </template>

          <el-form label-position="top">
            <!-- 文件选择 -->
            <el-form-item label="选择导出文件">
              <el-upload
                :auto-upload="false"
                :limit="1"
                accept=".json"
                :on-change="handleFileChange"
                :on-remove="handleFileRemove"
                drag
              >
                <div class="upload-hint">
                  <el-icon style="font-size: 28px; color: #909399"><UploadFilled /></el-icon>
                  <div>拖拽文件到此处，或点击选择</div>
                  <div class="upload-tip">仅支持 .json 文件</div>
                </div>
              </el-upload>
            </el-form-item>

            <!-- 文件元数据 -->
            <div v-if="fileMetadata" class="metadata-section">
              <el-divider content-position="left">文件信息</el-divider>
              <el-descriptions :column="1" border size="small">
                <el-descriptions-item label="来源实例">
                  {{ fileMetadata.source_instance_id }}
                </el-descriptions-item>
                <el-descriptions-item label="导出时间">
                  {{ formatDate(fileMetadata.exported_at) }}
                </el-descriptions-item>
                <el-descriptions-item label="包含分类">
                  {{ importableCategories.map(c => categoryLabels[c]).join("、") || "-" }}
                </el-descriptions-item>
                <el-descriptions-item
                  v-for="(count, table) in fileMetadata.counts"
                  :key="table"
                  :label="String(table)"
                >
                  {{ count }} 条记录
                </el-descriptions-item>
              </el-descriptions>
            </div>

            <!-- 导入选项 -->
            <template v-if="fileMetadata">
              <el-form-item label="导入分类" style="margin-top: 16px">
                <el-checkbox-group v-model="importCategories">
                  <el-checkbox
                    v-for="cat in importableCategories"
                    :key="cat"
                    :value="cat"
                  >
                    {{ categoryLabels[cat] }}
                  </el-checkbox>
                </el-checkbox-group>
              </el-form-item>

              <el-form-item label="冲突策略">
                <el-radio-group v-model="importStrategy">
                  <el-radio
                    v-for="(label, value) in strategyLabels"
                    :key="value"
                    :value="value"
                  >
                    {{ label }}
                  </el-radio>
                </el-radio-group>
              </el-form-item>

              <el-form-item>
                <el-button
                  :loading="previewing"
                  @click="handlePreview"
                >
                  预览
                </el-button>
                <el-button
                  type="primary"
                  :loading="importing"
                  :disabled="!previewResult"
                  @click="handleImport"
                >
                  执行导入
                </el-button>
              </el-form-item>
            </template>
          </el-form>

          <!-- 预览/导入结果 -->
          <div v-if="previewResult || importResult" class="result-section">
            <el-divider content-position="left">
              {{ importResult ? "导入结果" : "预览结果（dry-run）" }}
            </el-divider>

            <el-alert
              v-if="(importResult || previewResult)?.errors?.length"
              type="warning"
              :closable="false"
              style="margin-bottom: 12px"
            >
              <template #title>
                存在 {{ (importResult || previewResult)!.errors.length }} 个错误
              </template>
              <div v-for="(err, i) in (importResult || previewResult)!.errors" :key="i">
                {{ err }}
              </div>
            </el-alert>

            <el-table
              :data="formatStatsTable((importResult || previewResult)!.stats)"
              border
              size="small"
              style="width: 100%"
            >
              <el-table-column prop="table" label="表" />
              <el-table-column prop="inserted" label="插入" align="center" />
              <el-table-column prop="updated" label="更新" align="center" />
              <el-table-column prop="skipped" label="跳过" align="center" />
              <el-table-column prop="errors" label="错误" align="center" />
              <el-table-column prop="total" label="合计" align="center" />
            </el-table>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script lang="ts">
import { UploadFilled } from "@element-plus/icons-vue"

export default {
  components: { UploadFilled },
}
</script>

<style scoped>
.sync-view {
  max-width: 1400px;
}

.card-title {
  font-size: 16px;
  font-weight: 500;
}

.upload-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 20px 0;
  color: #606266;
}

.upload-tip {
  font-size: 12px;
  color: #909399;
}

.metadata-section {
  margin-bottom: 8px;
}

.result-section {
  margin-top: 8px;
}
</style>
