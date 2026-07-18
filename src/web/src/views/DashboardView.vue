<template>
  <ApiKeyGuideEmpty v-if="needsApiKey" />
  <div v-else class="dashboard-view">
    <!-- 统计卡片 - 第一行 -->
    <el-row :gutter="16" class="stats-row">
      <el-col :xs="24" :sm="12" :lg="6">
        <el-card shadow="hover" class="stat-card">
          <el-skeleton v-if="overviewLoading" :rows="1" animated />
          <el-statistic v-else title="推文总数" :value="overview?.tweets.total ?? 0" />
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :lg="6">
        <el-card shadow="hover" class="stat-card">
          <el-skeleton v-if="overviewLoading" :rows="1" animated />
          <el-statistic v-else title="活跃关注" :value="overview?.follows.active ?? 0" />
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :lg="6">
        <el-card shadow="hover" class="stat-card">
          <el-skeleton v-if="overviewLoading" :rows="1" animated />
          <el-statistic v-else title="摘要总数" :value="overview?.summaries.total ?? 0" />
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :lg="6">
        <el-card shadow="hover" class="stat-card">
          <el-skeleton v-if="overviewLoading" :rows="1" animated />
          <el-statistic v-else title="今日新增" :value="overview?.tweets.today_count ?? 0" />
        </el-card>
      </el-col>
    </el-row>

    <!-- 统计卡片 - 第二行 -->
    <el-row :gutter="16" class="stats-row">
      <el-col :xs="24" :sm="12" :lg="6">
        <el-card shadow="hover" class="stat-card">
          <el-skeleton v-if="overviewLoading" :rows="1" animated />
          <el-statistic v-else title="待摘要推文" :value="overview?.summaries.pending_tweets ?? 0" />
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :lg="6">
        <el-card shadow="hover" class="stat-card">
          <el-skeleton v-if="overviewLoading" :rows="1" animated />
          <el-statistic
            v-else
            title="数据库大小"
            :value="overview?.system.database_size_mb ?? 0"
            :precision="1"
            suffix="MB"
          />
        </el-card>
      </el-col>
    </el-row>

    <!-- 系统健康状态 -->
    <el-card class="section-card">
      <template #header>
        <div class="section-header">
          <span>服务连通性检查</span>
          <el-button
            text
            type="primary"
            size="small"
            :loading="configLoading"
            @click="refreshConfig"
          >
            刷新
          </el-button>
        </div>
      </template>
      <el-skeleton v-if="configLoading" :rows="2" animated />
      <el-alert
        v-else-if="configError"
        type="warning"
        :title="configError"
        :closable="false"
        show-icon
      />
      <div v-else-if="configData" class="health-section">
        <!-- Twitter API -->
        <div class="health-group">
          <div class="health-group-title">Twitter API</div>
          <div class="health-items">
            <div class="health-item">
              <el-tag
                :type="configData.twitter_api.status === 'healthy' ? 'success' : 'danger'"
                size="large"
                class="health-tag"
              >
                {{ configData.twitter_api.status }}
              </el-tag>
              <span v-if="configData.twitter_api.latency_ms" class="health-latency">
                {{ configData.twitter_api.latency_ms }}ms
              </span>
              <span v-if="configData.twitter_api.error" class="health-error">
                {{ configData.twitter_api.error }}
              </span>
            </div>
          </div>
        </div>

        <!-- 数据库 -->
        <div class="health-group">
          <div class="health-group-title">数据库</div>
          <div class="health-items">
            <div class="health-item">
              <el-tag
                :type="configData.database.status === 'healthy' ? 'success' : 'danger'"
                size="large"
                class="health-tag"
              >
                {{ configData.database.status }}
              </el-tag>
              <span v-if="configData.database.latency_ms" class="health-latency">
                {{ configData.database.latency_ms }}ms
              </span>
              <span v-if="configData.database.error" class="health-error">
                {{ configData.database.error }}
              </span>
            </div>
          </div>
        </div>

        <!-- 系统信息 -->
        <div v-if="overview?.system.server_start_time" class="health-group">
          <div class="health-group-title">系统</div>
          <div class="health-items">
            <div class="health-item">
              <span class="health-detail">
                启动时间: {{ formatFullDateTime(overview.system.server_start_time) }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 最近任务 -->
    <el-card class="section-card">
      <template #header>
        <span>最近任务</span>
      </template>
      <el-skeleton v-if="tasksLoading" :rows="3" animated />
      <el-alert
        v-else-if="tasksError"
        type="warning"
        :title="tasksError"
        :closable="false"
        show-icon
      />
      <el-table v-else :data="recentTasks" stripe>
        <el-table-column prop="task_id" label="任务 ID" min-width="200" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)" size="small">
              {{ getStatusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="150">
          <template #default="{ row }">
            {{ formatRelativeTime(row.created_at) }}
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue"
import { statusApi, configApi, tasksApi } from "@/api"
import ApiKeyGuideEmpty from "@/components/ApiKeyGuideEmpty.vue"
import { useApiKeyGuard } from "@/composables/useApiKeyGuard"
import { formatRelativeTime, formatFullDateTime } from "@/utils/format"
import type { StatusOverviewResponse, ConfigValidateResponse } from "@/types/status"
import type { TaskListItem } from "@/types"

/** 状态概览 */
const overview = ref<StatusOverviewResponse | null>(null)
const overviewLoading = ref(true)

/** 配置验证 */
const configData = ref<ConfigValidateResponse | null>(null)
const configLoading = ref(true)
const configError = ref("")

/** 最近任务 */
const recentTasks = ref<TaskListItem[]>([])
const tasksLoading = ref(true)
const tasksError = ref("")

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

/** 刷新配置验证 */
async function refreshConfig() {
  configLoading.value = true
  configError.value = ""
  try {
    configData.value = await configApi.validate()
  } catch {
    configError.value = "加载服务连通性检查失败"
  } finally {
    configLoading.value = false
  }
}

/** 并行加载所有数据 */
async function loadDashboardData() {
  const results = await Promise.allSettled([
    // 0: 状态概览
    statusApi.getOverview(),
    // 1: 配置验证
    configApi.validate(),
    // 2: 最近任务
    tasksApi.listTasks(),
  ])

  // 状态概览
  if (results[0].status === "fulfilled") {
    overview.value = results[0].value
  }
  overviewLoading.value = false

  // 配置验证
  if (results[1].status === "fulfilled") {
    configData.value = results[1].value
  } else {
    configError.value = "加载服务连通性检查失败"
  }
  configLoading.value = false

  // 最近任务
  if (results[2].status === "fulfilled") {
    recentTasks.value = results[2].value.slice(0, 5)
  } else {
    tasksError.value = "加载任务列表失败"
  }
  tasksLoading.value = false
}

const { needsApiKey } = useApiKeyGuard(loadDashboardData)
</script>

<style scoped>
.dashboard-view {
  max-width: 1200px;
  margin: 0 auto;
}

.stats-row {
  margin-bottom: 1.5rem;
}

.stat-card {
  height: 140px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.stat-card :deep(.el-card__body) {
  width: 100%;
}

.section-card {
  margin-bottom: 1.5rem;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.health-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.health-group-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin-bottom: 8px;
}

.health-items {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.health-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.health-tag {
  font-size: 14px;
}

.health-detail {
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.health-latency {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.health-error {
  font-size: 12px;
  color: var(--el-color-danger);
}
</style>
