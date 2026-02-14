<template>
  <div class="dashboard-view">
    <!-- 统计卡片 -->
    <el-row :gutter="16" class="stats-row">
      <el-col :xs="24" :sm="12" :lg="6">
        <el-card shadow="hover" class="stat-card">
          <el-skeleton v-if="tweetsLoading" :rows="1" animated />
          <el-alert
            v-else-if="tweetsError"
            type="warning"
            :title="tweetsError"
            :closable="false"
            show-icon
          />
          <el-statistic v-else title="推文总数" :value="tweetsTotal" />
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :lg="6">
        <el-card shadow="hover" class="stat-card">
          <el-skeleton v-if="followsLoading" :rows="1" animated />
          <el-alert
            v-else-if="followsError"
            type="warning"
            :title="followsError"
            :closable="false"
            show-icon
          />
          <el-statistic v-else title="活跃关注数" :value="activeFollowsCount" />
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :lg="6">
        <el-card shadow="hover" class="stat-card">
          <el-skeleton v-if="schedulerLoading" :rows="1" animated />
          <el-alert
            v-else-if="schedulerError"
            type="warning"
            :title="schedulerError"
            :closable="false"
            show-icon
          />
          <template v-else>
            <div class="scheduler-stat">
              <div class="stat-label">调度器状态</div>
              <div class="stat-value">
                <el-tag :type="schedulerConfig?.is_enabled ? 'success' : 'danger'" size="large">
                  {{ schedulerConfig?.is_enabled ? '已启用' : '已禁用' }}
                </el-tag>
              </div>
              <div class="stat-extra" v-if="schedulerConfig">
                间隔: {{ formatDuration(schedulerConfig.interval_seconds) }}
              </div>
            </div>
          </template>
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="12" :lg="6">
        <el-card shadow="hover" class="stat-card">
          <el-skeleton v-if="costLoading" :rows="1" animated />
          <el-alert
            v-else-if="costError"
            type="warning"
            :title="costError"
            :closable="false"
            show-icon
          />
          <el-statistic
            v-else
            title="摘要总成本"
            :value="costStats?.total_cost_usd ?? 0"
            :precision="4"
            prefix="$"
          />
        </el-card>
      </el-col>
    </el-row>

    <!-- 系统健康状态 -->
    <el-card class="section-card">
      <template #header>
        <span>系统健康状态</span>
      </template>
      <el-skeleton v-if="healthLoading" :rows="1" animated />
      <el-alert
        v-else-if="healthError"
        type="warning"
        :title="healthError"
        :closable="false"
        show-icon
      />
      <div v-else-if="healthData" class="health-tags">
        <el-tag
          v-for="(info, name) in healthData.components"
          :key="name"
          :type="info.status === 'healthy' ? 'success' : 'danger'"
          size="large"
          class="health-tag"
        >
          {{ name }}: {{ info.status }}
        </el-tag>
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
import { ref, onMounted } from "vue"
import { tweetsApi, followsApi, tasksApi, schedulerApi, healthApi, summariesApi } from "@/api"
import { formatRelativeTime, formatDuration } from "@/utils/format"
import type {
  ScheduleConfig,
  HealthResponse,
  CostStats,
  TaskListItem,
} from "@/types"

/** 推文统计 */
const tweetsTotal = ref(0)
const tweetsLoading = ref(true)
const tweetsError = ref("")

/** 活跃关注数 */
const activeFollowsCount = ref(0)
const followsLoading = ref(true)
const followsError = ref("")

/** 调度器配置 */
const schedulerConfig = ref<ScheduleConfig | null>(null)
const schedulerLoading = ref(true)
const schedulerError = ref("")

/** 成本统计 */
const costStats = ref<CostStats | null>(null)
const costLoading = ref(true)
const costError = ref("")

/** 健康状态 */
const healthData = ref<HealthResponse | null>(null)
const healthLoading = ref(true)
const healthError = ref("")

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

/** 并行加载所有数据 */
async function loadDashboardData() {
  const results = await Promise.allSettled([
    // 0: 推文总数
    tweetsApi.getList({ page: 1, page_size: 1 }),
    // 1: 关注列表
    followsApi.list(),
    // 2: 调度器配置
    schedulerApi.getConfig(),
    // 3: 成本统计
    summariesApi.getStats(),
    // 4: 健康状态
    healthApi.getStatus(),
    // 5: 最近任务
    tasksApi.listTasks(),
  ])

  // 推文总数
  if (results[0].status === "fulfilled") {
    tweetsTotal.value = results[0].value.total
  } else {
    tweetsError.value = "加载推文统计失败"
  }
  tweetsLoading.value = false

  // 活跃关注数
  if (results[1].status === "fulfilled") {
    activeFollowsCount.value = results[1].value.filter(
      (f) => f.is_active,
    ).length
  } else {
    followsError.value = "加载关注数据失败"
  }
  followsLoading.value = false

  // 调度器配置
  if (results[2].status === "fulfilled") {
    schedulerConfig.value = results[2].value
  } else {
    schedulerError.value = "加载调度器状态失败"
  }
  schedulerLoading.value = false

  // 成本统计
  if (results[3].status === "fulfilled") {
    costStats.value = results[3].value
  } else {
    costError.value = "加载成本统计失败"
  }
  costLoading.value = false

  // 健康状态
  if (results[4].status === "fulfilled") {
    healthData.value = results[4].value
  } else {
    healthError.value = "加载健康状态失败"
  }
  healthLoading.value = false

  // 最近任务
  if (results[5].status === "fulfilled") {
    recentTasks.value = results[5].value.slice(0, 5)
  } else {
    tasksError.value = "加载任务列表失败"
  }
  tasksLoading.value = false
}

onMounted(() => {
  loadDashboardData()
})
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

.scheduler-stat {
  text-align: center;
}

.stat-label {
  font-size: 12px;
  color: var(--el-text-color-regular);
  margin-bottom: 4px;
}

.stat-value {
  margin: 8px 0;
}

.stat-extra {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.section-card {
  margin-bottom: 1.5rem;
}

.health-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.health-tag {
  font-size: 14px;
}
</style>
