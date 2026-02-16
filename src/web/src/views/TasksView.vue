<template>
  <div class="tasks-view">
    <div class="page-header">
      <h1>任务监控</h1>
      <el-button
        type="primary"
        :icon="VideoPlay"
        @click="handleTriggerScraping"
        :loading="triggering"
      >
        立即抓取
      </el-button>
    </div>

    <!-- 当前任务状态 -->
    <el-card v-if="currentTask" class="current-task-card">
      <template #header>
        <div class="card-header">
          <span>当前任务</span>
          <el-tag :type="getStatusType(currentTask.status)">
            {{ getStatusText(currentTask.status) }}
          </el-tag>
        </div>
      </template>
      <div class="task-info">
        <div class="task-id">任务 ID: {{ currentTask.task_id }}</div>
        <el-progress
          v-if="currentTask.status === 'running'"
          :percentage="currentTask.progress.percentage"
          :format="() => `${currentTask!.progress.current}/${currentTask!.progress.total}`"
        />
        <div v-if="currentTask.error" class="task-error">
          <el-alert type="error" :closable="false">
            {{ currentTask.error }}
          </el-alert>
        </div>
        <div v-if="currentTask.result" class="task-result">
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="抓取推文数">
              {{ (currentTask.result as any).tweets_count || 0 }}
            </el-descriptions-item>
            <el-descriptions-item label="去重组数">
              {{ (currentTask.result as any).deduplication_count || 0 }}
            </el-descriptions-item>
            <el-descriptions-item label="摘要数">
              {{ (currentTask.result as any).summary_count || 0 }}
            </el-descriptions-item>
          </el-descriptions>
        </div>
      </div>
    </el-card>

    <!-- 任务历史 -->
    <el-card class="history-card">
      <template #header>
        <div class="card-header">
          <span>任务历史</span>
          <el-button link @click="loadTasks">刷新</el-button>
        </div>
      </template>

      <el-skeleton v-if="loading" :rows="3" animated />

      <el-table v-else :data="tasks" stripe>
        <el-table-column prop="task_id" label="任务 ID" width="200" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)" size="small">
              {{ getStatusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="150">
          <template #default="{ row }">
            <span v-if="row.status === 'completed' || row.status === 'failed'">
              {{ row.progress.current }}/{{ row.progress.total }}
            </span>
            <el-progress v-else :percentage="row.progress.percentage" :show-text="false" />
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="180">
          <template #default="{ row }">
            {{ formatLocalizedDateTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140">
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
              v-if="row.status !== 'running'"
              link
              type="danger"
              size="small"
              @click="handleDeleteTask(row)"
            >
              删除
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
          <el-descriptions-item label="进度">
            {{ selectedTask.progress.current }} / {{ selectedTask.progress.total }}
            ({{ selectedTask.progress.percentage.toFixed(1) }}%)
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
import { VideoPlay } from "@element-plus/icons-vue"
import { ElMessage, ElMessageBox } from "element-plus"
import { tasksApi, followsApi } from "@/api"
import { taskPollingService } from "@/services/polling"
import {
  formatLocalizedDateTime,
  formatFullDateTime,
  formatDuration,
  formatDurationMs,
  formatCostUsd,
  formatNumber,
} from "@/utils/format"
import type { TaskListItem, TaskStatusResponse } from "@/types"

/** 任务列表 */
const tasks = ref<TaskListItem[]>([])

/** 当前正在执行的任务 */
const currentTask = ref<TaskStatusResponse | null>(null)

/** 加载状态 */
const loading = ref(false)

/** 触发任务状态 */
const triggering = ref(false)

/** 详情对话框显示状态 */
const detailDialogVisible = ref(false)

/** 选中的任务 */
const selectedTask = ref<TaskStatusResponse | null>(null)

/** 轮询句柄 */
let pollingHandle: { cancel: () => void } | null = null

/** 加载任务列表 */
async function loadTasks() {
  loading.value = true
  try {
    tasks.value = await tasksApi.listTasks()
  } catch (error) {
    console.error("加载任务列表失败:", error)
  } finally {
    loading.value = false
  }
}

/** 触发抓取任务 */
async function handleTriggerScraping() {
  triggering.value = true
  try {
    // 先获取活跃账号列表
    const follows = await followsApi.list()
    const activeFollows = follows.filter((f) => f.is_active)

    if (activeFollows.length === 0) {
      ElMessage.warning("没有活跃的关注账号，无法抓取")
      return
    }

    const usernames = activeFollows.map((f) => f.username).join(",")

    const response = await tasksApi.triggerScraping({
      usernames,
      limit: 100,
    })

    // 设置当前任务
    currentTask.value = {
      task_id: response.task_id,
      status: "pending",
      result: null,
      error: null,
      created_at: new Date().toISOString(),
      started_at: null,
      completed_at: null,
      progress: { current: 0, total: 0, percentage: 0 },
      metadata: {},
    }

    // 启动轮询
    startPolling(response.task_id)

    // 刷新任务列表
    await loadTasks()
  } catch (error) {
    console.error("触发抓取任务失败:", error)
  } finally {
    triggering.value = false
  }
}

/** 启动任务状态轮询 */
function startPolling(taskId: string) {
  // 停止之前的轮询
  if (pollingHandle) {
    pollingHandle.cancel()
  }

  pollingHandle = taskPollingService.startPolling(
    taskId,
    async () => {
      const status = await tasksApi.getStatus(taskId)
      return status as TaskStatusResponse
    },
    (status) => {
      currentTask.value = status
    },
    (status) => {
      // 任务完成
      currentTask.value = status
      loadTasks()
    },
    (error) => {
      console.error("轮询任务状态失败:", error)
    },
  )
}

/** 停止轮询 */
function stopPolling() {
  if (pollingHandle) {
    pollingHandle.cancel()
    pollingHandle = null
  }
}

/** 删除任务 */
async function handleDeleteTask(task: TaskListItem) {
  try {
    await ElMessageBox.confirm("确定要删除此任务？", "确认删除", {
      confirmButtonText: "确定",
      cancelButtonText: "取消",
      type: "warning",
    })

    await tasksApi.deleteTask(task.task_id)
    ElMessage.success("任务已删除")
    await loadTasks()
  } catch (error) {
    // 用户取消时 ElMessageBox 会抛出 'cancel'
    if (error !== "cancel") {
      console.error("删除任务失败:", error)
      ElMessage.error("删除任务失败")
    }
  }
}

/** 查看任务详情 */
async function handleViewDetail(task: TaskListItem) {
  try {
    const detail = await tasksApi.getStatus(task.task_id)
    selectedTask.value = detail
    detailDialogVisible.value = true
  } catch (error) {
    console.error("获取任务详情失败:", error)
  }
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
  loadTasks()
})

/** 组件卸载时清理轮询 */
onUnmounted(() => {
  stopPolling()
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

.current-task-card {
  margin-bottom: 1.5rem;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.task-info {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.task-id {
  font-family: monospace;
  color: #666;
}

.task-error {
  margin-top: 0.5rem;
}

.task-result {
  margin-top: 0.5rem;
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
