<template>
  <div class="tasks-view">
    <div class="page-header">
      <h1>任务监控</h1>
    </div>

    <!-- 活跃任务（内存中的 pending / running 任务） -->
    <el-card class="active-tasks-card">
      <template #header>
        <div class="card-header">
          <span>
            活跃任务
            <el-badge
              v-if="activeTasks.length > 0"
              :value="activeTasks.length"
              type="warning"
              class="active-badge"
            />
          </span>
          <el-button link @click="loadActiveTasks">刷新</el-button>
        </div>
      </template>

      <el-empty
        v-if="activeTasks.length === 0"
        description="当前没有正在执行或等待中的任务"
        :image-size="60"
      />

      <el-table v-else :data="activeTasks" stripe>
        <el-table-column prop="task_name" label="任务名称" min-width="160" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)" size="small">
              {{ getStatusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="200">
          <template #default="{ row }">
            <el-progress
              v-if="row.status === 'running' && row.progress.total > 0"
              :percentage="row.progress.percentage"
              :format="() => `${row.progress.current}/${row.progress.total}`"
            />
            <span v-else-if="row.status === 'pending'" class="text-muted">
              等待执行...
            </span>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="180">
          <template #default="{ row }">
            {{ row.created_at ? formatLocalizedDateTime(row.created_at) : '-' }}
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 任务历史（持久化，重启后保留） -->
    <el-card class="history-card">
      <template #header>
        <div class="card-header">
          <span>任务历史</span>
          <el-button link @click="loadHistory">刷新</el-button>
        </div>
      </template>

      <el-skeleton v-if="loading" :rows="3" animated />

      <el-empty v-else-if="historyTasks.length === 0" description="暂无任务历史" />

      <el-table v-else :data="historyTasks" stripe>
        <el-table-column prop="task_name" label="任务名称" min-width="160" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)" size="small">
              {{ getStatusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="120">
          <template #default="{ row }">
            {{ row.duration_seconds != null ? formatDuration(row.duration_seconds) : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="180">
          <template #default="{ row }">
            {{ formatLocalizedDateTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button
              link
              type="primary"
              size="small"
              @click="handleViewHistoryDetail(row)"
            >
              详情
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 任务详情对话框 -->
    <el-dialog
      v-model="detailDialogVisible"
      title="任务详情"
      width="600px"
    >
      <div v-if="selectedTask">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="任务名称" v-if="selectedTask.task_name">
            {{ selectedTask.task_name }}
          </el-descriptions-item>
          <el-descriptions-item label="任务 ID">
            {{ selectedTask.task_id }}
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="getStatusType(selectedTask.status)">
              {{ getStatusText(selectedTask.status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="创建时间">
            {{ formatFullDateTime(selectedTask.created_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="开始时间" v-if="selectedTask.started_at">
            {{ formatFullDateTime(selectedTask.started_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="完成时间" v-if="selectedTask.completed_at">
            {{ formatFullDateTime(selectedTask.completed_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="执行耗时" v-if="selectedTask.duration_seconds != null">
            {{ formatDuration(selectedTask.duration_seconds) }}
          </el-descriptions-item>
          <el-descriptions-item label="错误信息" v-if="selectedTask.error">
            <el-text type="danger">{{ selectedTask.error }}</el-text>
          </el-descriptions-item>
        </el-descriptions>

        <!-- 执行结果：结构化展示 -->
        <div v-if="selectedTask.result" class="result-section">
          <h4>执行结果</h4>

          <!-- 摘要任务结果 -->
          <template v-if="isSummarizationResult(selectedTask.result)">
            <div class="stat-grid">
              <div class="stat-card">
                <div class="stat-value">{{ r(selectedTask.result).total_tweets_summarized }} / {{ r(selectedTask.result).total_tweets_requested }}</div>
                <div class="stat-label">成功摘要 / 请求总数</div>
              </div>
              <div class="stat-card">
                <div class="stat-value">{{ formatNumber(r(selectedTask.result).total_tokens) }}</div>
                <div class="stat-label">Token 用量</div>
              </div>
              <div class="stat-card">
                <div class="stat-value">{{ formatCostUsd(r(selectedTask.result).total_cost_usd) }}</div>
                <div class="stat-label">费用</div>
              </div>
              <div class="stat-card">
                <div class="stat-value">{{ formatDurationMs(r(selectedTask.result).processing_time_ms) }}</div>
                <div class="stat-label">处理耗时</div>
              </div>
            </div>
            <el-descriptions :column="2" border size="small" class="result-details">
              <el-descriptions-item label="缓存命中">
                {{ r(selectedTask.result).cache_hits }}
              </el-descriptions-item>
              <el-descriptions-item label="缓存未命中">
                {{ r(selectedTask.result).cache_misses }}
              </el-descriptions-item>
              <el-descriptions-item label="模型提供商">
                <span v-for="(count, provider) in (r(selectedTask.result).providers_used || {})" :key="String(provider)">
                  {{ provider }}: {{ count }}次
                </span>
                <span v-if="!r(selectedTask.result).providers_used || Object.keys(r(selectedTask.result).providers_used).length === 0">-</span>
              </el-descriptions-item>
              <el-descriptions-item label="分块完成">
                {{ r(selectedTask.result).chunks?.completed || 0 }} / {{ r(selectedTask.result).chunks?.total || 0 }}
                <el-text v-if="r(selectedTask.result).chunks?.failed" type="danger" style="margin-left: 4px">
                  ({{ r(selectedTask.result).chunks.failed }} 失败)
                </el-text>
              </el-descriptions-item>
            </el-descriptions>
            <!-- 失败推文折叠 -->
            <el-collapse v-if="r(selectedTask.result).failed_tweet_ids?.length" class="result-collapse">
              <el-collapse-item :title="`失败推文 (${r(selectedTask.result).failed_tweet_ids.length})`">
                <div v-for="(item, idx) in r(selectedTask.result).failed_tweet_ids.slice(0, 20)" :key="idx" class="failed-item">
                  {{ item.tweet_id }}: {{ item.reason }}
                </div>
                <el-text v-if="r(selectedTask.result).failed_tweet_ids.length > 20" type="info" size="small">
                  ...还有 {{ r(selectedTask.result).failed_tweet_ids.length - 20 }} 条
                </el-text>
              </el-collapse-item>
            </el-collapse>
          </template>

          <!-- 抓取任务结果 -->
          <template v-else-if="isScrapingResult(selectedTask.result)">
            <div class="stat-grid">
              <div class="stat-card">
                <div class="stat-value">{{ r(selectedTask.result).successful_users }} / {{ r(selectedTask.result).total_users }}</div>
                <div class="stat-label">成功用户 / 总用户</div>
              </div>
              <div class="stat-card">
                <div class="stat-value">{{ r(selectedTask.result).new_tweets }}</div>
                <div class="stat-label">新推文</div>
              </div>
              <div class="stat-card">
                <div class="stat-value">{{ r(selectedTask.result).total_tweets }}</div>
                <div class="stat-label">抓取总数</div>
              </div>
              <div class="stat-card">
                <div class="stat-value">{{ formatDuration(r(selectedTask.result).elapsed_seconds) }}</div>
                <div class="stat-label">耗时</div>
              </div>
            </div>
            <el-descriptions :column="2" border size="small" class="result-details" v-if="r(selectedTask.result).failed_users > 0 || r(selectedTask.result).skipped_tweets > 0">
              <el-descriptions-item label="失败用户" v-if="r(selectedTask.result).failed_users > 0">
                <el-text type="danger">{{ r(selectedTask.result).failed_users }}</el-text>
              </el-descriptions-item>
              <el-descriptions-item label="跳过推文" v-if="r(selectedTask.result).skipped_tweets > 0">
                {{ r(selectedTask.result).skipped_tweets }}
              </el-descriptions-item>
              <el-descriptions-item label="错误数" v-if="r(selectedTask.result).total_errors > 0">
                <el-text type="danger">{{ r(selectedTask.result).total_errors }}</el-text>
              </el-descriptions-item>
            </el-descriptions>
          </template>

          <!-- 未知类型：fallback 为 JSON -->
          <template v-else>
            <pre class="result-json">{{ JSON.stringify(selectedTask.result, null, 2) }}</pre>
          </template>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue"
import { tasksApi } from "@/api"
import {
  formatLocalizedDateTime,
  formatFullDateTime,
  formatDuration,
  formatDurationMs,
  formatCostUsd,
  formatNumber,
} from "@/utils/format"
import type { TaskHistoryItem, TaskListItem } from "@/types"

/** 活跃任务列表（pending + running，来自 TaskRegistry 内存） */
const activeTasks = ref<TaskListItem[]>([])

/** 持久化的任务历史列表 */
const historyTasks = ref<TaskHistoryItem[]>([])

/** 加载状态 */
const loading = ref(false)

/** 详情对话框显示状态 */
const detailDialogVisible = ref(false)

/** 选中的任务（历史记录） */
const selectedTask = ref<TaskHistoryItem | null>(null)

/** 活跃任务轮询定时器 */
let activeTasksTimer: ReturnType<typeof setInterval> | null = null

/** 轮询间隔（毫秒） */
const ACTIVE_TASKS_POLL_INTERVAL = 3000

/** 加载活跃任务（pending + running） */
async function loadActiveTasks() {
  try {
    const allTasks = await tasksApi.listTasks()
    const newActiveTasks = allTasks.filter(
      (t) => t.status === "pending" || t.status === "running",
    )
    // 活跃任务数减少时（有任务完成），自动刷新历史列表
    if (activeTasks.value.length > 0 && newActiveTasks.length < activeTasks.value.length) {
      loadHistory()
    }
    activeTasks.value = newActiveTasks
  } catch (error) {
    console.error("加载活跃任务失败:", error)
  }
}

/** 启动活跃任务轮询 */
function startActiveTasksPolling() {
  stopActiveTasksPolling()
  loadActiveTasks()
  activeTasksTimer = setInterval(loadActiveTasks, ACTIVE_TASKS_POLL_INTERVAL)
}

/** 停止活跃任务轮询 */
function stopActiveTasksPolling() {
  if (activeTasksTimer) {
    clearInterval(activeTasksTimer)
    activeTasksTimer = null
  }
}

/** 加载持久化的任务历史 */
async function loadHistory() {
  loading.value = true
  try {
    historyTasks.value = await tasksApi.getHistory()
  } catch (error) {
    console.error("加载任务历史失败:", error)
  } finally {
    loading.value = false
  }
}

/** 查看历史任务详情 */
function handleViewHistoryDetail(task: TaskHistoryItem) {
  selectedTask.value = task
  detailDialogVisible.value = true
}

/** 获取状态类型 */
function getStatusType(status: string): "success" | "warning" | "danger" | "info" {
  switch (status) {
    case "completed":
      return "success"
    case "running":
      return "warning"
    case "failed":
      return "danger"
    default:
      return "info"
  }
}

/** 获取状态文本 */
function getStatusText(status: string): string {
  const statusMap: Record<string, string> = {
    pending: "等待中",
    running: "执行中",
    completed: "已完成",
    failed: "失败",
  }
  return statusMap[status] || status
}

/** result 类型断言辅助（避免模板中大量 as any） */
function r(result: Record<string, unknown>): Record<string, any> {
  return result as Record<string, any>
}

/** 判断是否为摘要任务结果 */
function isSummarizationResult(result: Record<string, unknown>): boolean {
  return "total_tweets_requested" in result || "chunk_results" in result
}

/** 判断是否为抓取任务结果 */
function isScrapingResult(result: Record<string, unknown>): boolean {
  return "total_users" in result && "new_tweets" in result
}

/** 组件挂载时加载数据 */
onMounted(() => {
  loadHistory()
  startActiveTasksPolling()
})

/** 组件卸载时清理轮询 */
onUnmounted(() => {
  stopActiveTasksPolling()
})
</script>

<style scoped>
.tasks-view {
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

.active-tasks-card {
  margin-bottom: 1.5rem;
}

.active-badge {
  margin-left: 8px;
}

.text-muted {
  color: #909399;
  font-size: 0.875rem;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.history-card {
  margin-bottom: 1.5rem;
}

.result-section {
  margin-top: 1.5rem;
}

.result-section h4 {
  margin: 0 0 0.75rem 0;
  color: #333;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}

.stat-card {
  background: #f5f7fa;
  border-radius: 8px;
  padding: 14px 12px;
  text-align: center;
}

.stat-value {
  font-size: 1.25rem;
  font-weight: 600;
  color: #303133;
  line-height: 1.4;
}

.stat-label {
  font-size: 0.75rem;
  color: #909399;
  margin-top: 4px;
}

.result-details {
  margin-bottom: 12px;
}

.result-collapse {
  margin-top: 8px;
}

.failed-item {
  font-size: 0.8125rem;
  font-family: monospace;
  color: #606266;
  padding: 2px 0;
  word-break: break-all;
}

.result-json {
  background-color: #f5f7fa;
  padding: 1rem;
  border-radius: 4px;
  overflow-x: auto;
  font-size: 0.875rem;
}
</style>
