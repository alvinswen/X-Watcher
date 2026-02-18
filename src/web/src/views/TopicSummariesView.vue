<template>
  <div class="topic-summaries-view">
    <div class="page-header">
      <h1>主题摘要</h1>
      <el-button type="primary" :icon="Plus" @click="handleCreateTask">
        创建摘要任务
      </el-button>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <el-select
        v-model="filterTopicId"
        placeholder="按主题筛选"
        clearable
        style="width: 200px"
        @change="loadTasks"
      >
        <el-option
          v-for="t in allTopics"
          :key="t.id"
          :label="t.name"
          :value="t.id"
        />
      </el-select>
    </div>

    <!-- 加载状态 -->
    <el-skeleton v-if="loading" :rows="5" animated />

    <!-- 任务列表 -->
    <el-table v-else :data="tasks" stripe border style="width: 100%">
      <el-table-column prop="topic_name" label="主题名称" width="160">
        <template #default="{ row }">
          {{ row.topic_name || '全部账号' }}
        </template>
      </el-table-column>
      <el-table-column label="时间跨度" width="120" align="center">
        <template #default="{ row }">
          {{ row.time_span_hours }} 小时
        </template>
      </el-table-column>
      <el-table-column label="截止时间" width="180">
        <template #default="{ row }">
          <el-tooltip :content="formatFullDateTime(row.deadline)" placement="top">
            <span>{{ formatRelativeTime(row.deadline) }}</span>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100" align="center">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)" size="small">
            {{ statusText(row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="180">
        <template #default="{ row }">
          <el-tooltip :content="formatFullDateTime(row.created_at)" placement="top">
            <span>{{ formatRelativeTime(row.created_at) }}</span>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button
            link
            type="primary"
            size="small"
            @click="handleViewDetail(row)"
          >
            详情
          </el-button>
          <el-button
            v-if="row.status === 'completed'"
            link
            type="primary"
            size="small"
            @click="handleDownloadSummary(row)"
          >
            下载
          </el-button>
          <el-button
            link
            type="danger"
            size="small"
            @click="handleDeleteTask(row)"
            :disabled="submitting"
          >
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 创建摘要任务对话框 -->
    <el-dialog
      v-model="createDialogVisible"
      title="创建摘要任务"
      width="520px"
    >
      <el-form
        ref="createFormRef"
        :model="createFormData"
        :rules="createFormRules"
        label-width="100px"
      >
        <el-form-item label="主题" prop="topic_id">
          <el-select
            v-model="createFormData.topic_id"
            placeholder="请选择主题"
            style="width: 100%"
          >
            <el-option key="all" label="全部账号" :value="null" />
            <el-option
              v-for="t in allTopics"
              :key="t.id"
              :label="t.name"
              :value="t.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="时间跨度" prop="time_span_hours">
          <el-input-number
            v-model="createFormData.time_span_hours"
            :min="1"
            :max="720"
            controls-position="right"
            style="width: 100%"
          />
          <div class="form-hint">收集截止时间前多少小时内的推文</div>
        </el-form-item>
        <el-form-item label="截止时间" prop="deadline">
          <el-date-picker
            v-model="createFormData.deadline"
            type="datetime"
            placeholder="选择截止时间"
            format="YYYY-MM-DD HH:mm:ss"
            value-format="YYYY-MM-DDTHH:mm:ss"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="自定义提示词" prop="custom_prompt">
          <el-input
            v-model="createFormData.custom_prompt"
            type="textarea"
            :rows="8"
            placeholder="自定义 LLM 提示词（可选）"
            maxlength="5000"
            show-word-limit
          />
          <div class="form-hint">
            支持模板变量：{account_count}（账号数）、{time_span}（时间跨度）、{tweet_count}（推文数）、{tweets_content}（推文内容）
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSubmitCreate" :loading="submitting">
          创建
        </el-button>
      </template>
    </el-dialog>

    <!-- 任务详情抽屉 -->
    <el-drawer
      v-model="detailDrawerVisible"
      title="摘要任务详情"
      size="600px"
    >
      <template v-if="taskDetail">
        <!-- 基本信息 -->
        <el-descriptions title="基本信息" :column="2" border>
          <el-descriptions-item label="主题">
            {{ taskDetail.topic_name || '全部账号' }}
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusTagType(taskDetail.status)" size="small">
              {{ statusText(taskDetail.status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="时间跨度">
            {{ taskDetail.time_span_hours }} 小时
          </el-descriptions-item>
          <el-descriptions-item label="截止时间">
            {{ formatFullDateTime(taskDetail.deadline) }}
          </el-descriptions-item>
          <el-descriptions-item label="创建时间">
            {{ formatFullDateTime(taskDetail.created_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="开始时间">
            {{ formatFullDateTime(taskDetail.started_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="完成时间" :span="2">
            {{ formatFullDateTime(taskDetail.completed_at) }}
          </el-descriptions-item>
        </el-descriptions>

        <!-- 自定义提示词 -->
        <div v-if="taskDetail.custom_prompt" class="detail-section">
          <h4>自定义提示词</h4>
          <div class="custom-prompt-content">{{ taskDetail.custom_prompt }}</div>
        </div>

        <!-- 错误信息 -->
        <div v-if="taskDetail.status === 'failed' && taskDetail.error_message" class="detail-section">
          <el-alert
            title="任务失败"
            type="error"
            :description="taskDetail.error_message"
            :closable="false"
            show-icon
          />
        </div>

        <!-- 摘要内容 -->
        <template v-if="taskDetail.summary">
          <div class="detail-section">
            <div style="display: flex; align-items: center; justify-content: space-between;">
              <h4>摘要内容</h4>
              <el-button type="primary" size="small" @click="handleDownloadDetailSummary">
                下载 Markdown
              </el-button>
            </div>
            <div class="summary-content">{{ taskDetail.summary.content }}</div>
          </div>

          <!-- 元数据 -->
          <el-descriptions title="摘要元数据" :column="2" border class="detail-section">
            <el-descriptions-item label="LLM 提供商">
              {{ taskDetail.summary.llm_provider }}
            </el-descriptions-item>
            <el-descriptions-item label="模型">
              {{ taskDetail.summary.llm_model }}
            </el-descriptions-item>
            <el-descriptions-item label="Prompt Tokens">
              {{ formatNumber(taskDetail.summary.prompt_tokens) }}
            </el-descriptions-item>
            <el-descriptions-item label="Completion Tokens">
              {{ formatNumber(taskDetail.summary.completion_tokens) }}
            </el-descriptions-item>
            <el-descriptions-item label="Total Tokens">
              {{ formatNumber(taskDetail.summary.total_tokens) }}
            </el-descriptions-item>
            <el-descriptions-item label="成本">
              {{ formatCostUsd(taskDetail.summary.cost_usd) }}
            </el-descriptions-item>
            <el-descriptions-item label="推文数">
              {{ taskDetail.summary.tweet_count }}
            </el-descriptions-item>
            <el-descriptions-item label="账号数">
              {{ taskDetail.summary.account_count }}
            </el-descriptions-item>
          </el-descriptions>
        </template>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, reactive } from "vue"
import { Plus } from "@element-plus/icons-vue"
import { ElMessageBox, ElMessage, type FormInstance, type FormRules } from "element-plus"
import { topicsApi } from "@/api"
import { formatRelativeTime, formatFullDateTime, formatCostUsd, formatNumber } from "@/utils/format"
import type {
  TopicListItem,
  TopicSummaryTask,
  TopicSummaryTaskDetail,
  TopicSummaryTaskStatus,
} from "@/types/topic"

// ==================== 任务列表状态 ====================

/** 任务列表 */
const tasks = ref<TopicSummaryTask[]>([])

/** 主题列表（用于筛选和创建） */
const allTopics = ref<TopicListItem[]>([])

/** 加载状态 */
const loading = ref(false)

/** 提交状态 */
const submitting = ref(false)

/** 筛选主题 ID */
const filterTopicId = ref<number | undefined>(undefined)

/** 轮询定时器 */
let pollTimer: ReturnType<typeof setInterval> | null = null

/** 默认提示词模板 */
const defaultPrompt = ref("")

// ==================== 创建任务状态 ====================

/** 创建对话框可见性 */
const createDialogVisible = ref(false)

/** 创建表单引用 */
const createFormRef = ref<FormInstance>()

/** 创建表单数据 */
const createFormData = reactive({
  topic_id: null as number | null,
  time_span_hours: 24,
  deadline: "",
  custom_prompt: "",
})

/** 创建表单验证规则 */
const createFormRules: FormRules = {
  time_span_hours: [
    { required: true, message: "请输入时间跨度", trigger: "blur" },
  ],
  deadline: [
    { required: true, message: "请选择截止时间", trigger: "change" },
  ],
}

// ==================== 详情状态 ====================

/** 详情抽屉可见性 */
const detailDrawerVisible = ref(false)

/** 任务详情 */
const taskDetail = ref<TopicSummaryTaskDetail | null>(null)

// ==================== 状态工具函数 ====================

/** 状态标签颜色 */
function statusTagType(status: TopicSummaryTaskStatus): string {
  switch (status) {
    case "pending": return "info"
    case "running": return "warning"
    case "completed": return "success"
    case "failed": return "danger"
    default: return "info"
  }
}

/** 状态中文文本 */
function statusText(status: TopicSummaryTaskStatus): string {
  switch (status) {
    case "pending": return "等待中"
    case "running": return "运行中"
    case "completed": return "已完成"
    case "failed": return "失败"
    default: return "未知"
  }
}

// ==================== 数据加载方法 ====================

/** 加载主题列表 */
async function loadAllTopics() {
  try {
    allTopics.value = await topicsApi.list()
  } catch (error) {
    console.error("加载主题列表失败:", error)
  }
}

/** 加载默认提示词 */
async function loadDefaultPrompt() {
  try {
    const data = await topicsApi.getDefaultPrompt()
    defaultPrompt.value = data.prompt
  } catch (error) {
    console.error("加载默认提示词失败:", error)
  }
}

/** 加载任务列表 */
async function loadTasks() {
  loading.value = true
  try {
    tasks.value = await topicsApi.listTasks(filterTopicId.value)
    updatePolling()
  } catch (error) {
    console.error("加载摘要任务列表失败:", error)
  } finally {
    loading.value = false
  }
}

// ==================== 轮询逻辑 ====================

/** 检查是否有进行中的任务，决定是否开始/停止轮询 */
function updatePolling() {
  const hasActiveTask = tasks.value.some(
    (t) => t.status === "pending" || t.status === "running",
  )
  if (hasActiveTask) {
    startPolling()
  } else {
    stopPolling()
  }
}

/** 开始轮询 */
function startPolling() {
  if (pollTimer) return // 已在轮询
  pollTimer = setInterval(pollTasks, 2000)
}

/** 停止轮询 */
function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

/** 轮询加载任务列表 */
async function pollTasks() {
  try {
    tasks.value = await topicsApi.listTasks(filterTopicId.value)
    // 检查是否仍需轮询
    const hasActiveTask = tasks.value.some(
      (t) => t.status === "pending" || t.status === "running",
    )
    if (!hasActiveTask) {
      stopPolling()
    }
  } catch (error) {
    console.error("轮询任务列表失败:", error)
    stopPolling()
  }
}

// ==================== 创建任务方法 ====================

/** 打开创建对话框 */
function handleCreateTask() {
  createFormData.topic_id = null
  createFormData.time_span_hours = 24
  createFormData.deadline = ""
  createFormData.custom_prompt = defaultPrompt.value
  createDialogVisible.value = true
}

/** 提交创建 */
async function handleSubmitCreate() {
  if (!createFormRef.value) {
    ElMessage.warning("表单未初始化，请关闭对话框后重试")
    return
  }

  try {
    await createFormRef.value.validate()
  } catch {
    // validate() 验证失败时会 reject，Element Plus 已自动显示字段错误提示
    return
  }

  submitting.value = true
  try {
    // 将本地时间转换为 UTC ISO 字符串
    const localDate = new Date(createFormData.deadline)
    const customPrompt = createFormData.custom_prompt === defaultPrompt.value
      ? null
      : (createFormData.custom_prompt || null)
    await topicsApi.createTask({
      topic_id: createFormData.topic_id,
      time_span_hours: createFormData.time_span_hours,
      deadline: localDate.toISOString(),
      custom_prompt: customPrompt,
    })
    ElMessage.success("摘要任务已创建")
    createDialogVisible.value = false
    await loadTasks()
  } catch (error) {
    console.error("创建摘要任务失败:", error)
  } finally {
    submitting.value = false
  }
}

// ==================== 详情和删除方法 ====================

/** 查看任务详情 */
async function handleViewDetail(task: TopicSummaryTask) {
  detailDrawerVisible.value = true
  taskDetail.value = null
  try {
    taskDetail.value = await topicsApi.getTask(task.id)
  } catch (error) {
    console.error("加载任务详情失败:", error)
  }
}

/** 触发浏览器下载文本文件 */
function downloadAsFile(content: string, filename: string) {
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" })
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

/** 生成摘要文件名 */
function buildSummaryFilename(topicName: string | null, createdAt: string): string {
  const name = topicName || "全部账号"
  const dateStr = new Date(createdAt).toISOString().slice(0, 10)
  return `摘要_${name}_${dateStr}.md`
}

/** 从列表下载摘要 */
async function handleDownloadSummary(task: TopicSummaryTask) {
  try {
    const detail = await topicsApi.getTask(task.id)
    if (!detail.summary) {
      ElMessage.warning("摘要内容不可用")
      return
    }
    downloadAsFile(detail.summary.content, buildSummaryFilename(task.topic_name, task.created_at))
  } catch (error) {
    console.error("下载摘要失败:", error)
    ElMessage.error("下载摘要失败")
  }
}

/** 从详情抽屉下载摘要 */
function handleDownloadDetailSummary() {
  if (!taskDetail.value?.summary) return
  downloadAsFile(
    taskDetail.value.summary.content,
    buildSummaryFilename(taskDetail.value.topic_name, taskDetail.value.created_at),
  )
}

/** 删除任务 */
async function handleDeleteTask(task: TopicSummaryTask) {
  try {
    await ElMessageBox.confirm(
      `确定要删除此摘要任务吗？此操作不可恢复。`,
      "确认删除",
      {
        type: "warning",
        confirmButtonText: "删除",
        confirmButtonClass: "el-button--danger",
      },
    )
    submitting.value = true
    await topicsApi.deleteTask(task.id)
    ElMessage.success("摘要任务已删除")
    await loadTasks()
  } catch (error) {
    if (error !== "cancel") {
      console.error("删除摘要任务失败:", error)
    }
  } finally {
    submitting.value = false
  }
}

// ==================== 初始化 ====================

onMounted(() => {
  loadAllTopics()
  loadTasks()
  loadDefaultPrompt()
})

onUnmounted(() => {
  stopPolling()
})
</script>

<style scoped>
.topic-summaries-view {
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1.5rem;
}

.page-header h1 {
  margin: 0;
  font-size: 1.5rem;
  color: #333;
}

.filter-bar {
  margin-bottom: 1rem;
}

.form-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
}

.detail-section {
  margin-top: 20px;
}

.detail-section h4 {
  margin: 0 0 10px;
  font-size: 14px;
  color: var(--el-text-color-primary);
}

.summary-content {
  padding: 16px;
  background-color: var(--el-fill-color-light);
  border-radius: 4px;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 14px;
  line-height: 1.8;
  max-height: 400px;
  overflow-y: auto;
}

.custom-prompt-content {
  padding: 12px;
  background-color: var(--el-fill-color-lighter);
  border-radius: 4px;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
</style>
