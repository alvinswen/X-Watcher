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

        <div v-if="selectedTask.result" class="result-section">
          <h4>执行结果</h4>
          <pre>{{ JSON.stringify(selectedTask.result, null, 2) }}</pre>
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
import { formatLocalizedDateTime, formatFullDateTime } from "@/utils/format"
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

.result-section pre {
  background-color: #f5f7fa;
  padding: 1rem;
  border-radius: 4px;
  overflow-x: auto;
  font-size: 0.875rem;
}
</style>
