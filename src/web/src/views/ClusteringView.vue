<script setup lang="ts">
import { ref, computed, onMounted } from "vue"
import { ElMessage, ElMessageBox } from "element-plus"
import { clusteringApi } from "@/api/clustering"
import type {
  ClusteringRunSummary,
  ClusteringRunDetail,
  ClusterAssignment,
} from "@/types/clustering"

// ── 状态 ──

const runs = ref<ClusteringRunSummary[]>([])
const selectedRun = ref<ClusteringRunDetail | null>(null)
const loading = ref(false)
const runLoading = ref(false)
const detailLoading = ref(false)

// 运行参数
const minTweets = ref(20)
const linkageMethod = ref("average")

// 重切割参数
const recutMode = ref<"height" | "clusters">("height")
const recutHeight = ref<number | undefined>(undefined)
const recutClusters = ref<number | undefined>(undefined)

// ── 计算属性 ──

const clusterGroups = computed(() => {
  if (!selectedRun.value) return []
  const groups = new Map<number, ClusterAssignment[]>()
  for (const a of selectedRun.value.assignments) {
    if (!groups.has(a.cluster_id)) groups.set(a.cluster_id, [])
    groups.get(a.cluster_id)!.push(a)
  }
  return Array.from(groups.entries())
    .sort(([a], [b]) => a - b)
    .map(([clusterId, members]) => ({
      clusterId,
      members,
      centroid: computeCentroid(members),
      totalTweets: members.reduce((sum, m) => sum + m.tweet_count, 0),
    }))
})

const availableClusterIds = computed(() => {
  if (!selectedRun.value) return []
  const ids = new Set(selectedRun.value.assignments.map((a) => a.cluster_id))
  return Array.from(ids).sort((a, b) => a - b)
})

// ── 方法 ──

function computeCentroid(members: ClusterAssignment[]): number[] {
  const centroid = new Array(24).fill(0)
  for (const m of members) {
    for (let i = 0; i < 24; i++) {
      centroid[i] += m.hourly_distribution[i]
    }
  }
  const n = members.length
  return centroid.map((v) => v / n)
}

function formatDatetime(dt: string | null): string {
  if (!dt) return "-"
  return new Date(dt).toLocaleString("zh-CN")
}

function statusType(s: string): string {
  switch (s) {
    case "completed":
      return "success"
    case "running":
      return ""
    case "failed":
      return "danger"
    default:
      return "info"
  }
}

function statusLabel(s: string): string {
  switch (s) {
    case "completed":
      return "已完成"
    case "running":
      return "运行中"
    case "failed":
      return "失败"
    case "pending":
      return "等待中"
    default:
      return s
  }
}

async function loadRuns() {
  loading.value = true
  try {
    runs.value = await clusteringApi.listRuns()
  } catch {
    // error handled by interceptor
  } finally {
    loading.value = false
  }
}

async function handleRunClustering() {
  runLoading.value = true
  try {
    const result = await clusteringApi.runClustering({
      min_tweets: minTweets.value,
      linkage_method: linkageMethod.value,
    })
    selectedRun.value = result
    ElMessage.success(`聚类完成：${result.num_clusters} 个组，${result.num_accounts} 个账号`)
    await loadRuns()
  } catch {
    // error handled by interceptor
  } finally {
    runLoading.value = false
  }
}

async function selectRun(run: ClusteringRunSummary) {
  if (run.status !== "completed") {
    selectedRun.value = null
    return
  }
  detailLoading.value = true
  try {
    selectedRun.value = await clusteringApi.getRun(run.id)
    if (selectedRun.value.cut_height != null) {
      recutHeight.value = selectedRun.value.cut_height
    }
    if (selectedRun.value.num_clusters != null) {
      recutClusters.value = selectedRun.value.num_clusters
    }
  } catch {
    // error handled by interceptor
  } finally {
    detailLoading.value = false
  }
}

async function handleReCut() {
  if (!selectedRun.value) return
  detailLoading.value = true
  try {
    const req =
      recutMode.value === "height"
        ? { cut_height: recutHeight.value }
        : { num_clusters: recutClusters.value }
    selectedRun.value = await clusteringApi.reCut(selectedRun.value.id, req)
    ElMessage.success(`重切割完成：${selectedRun.value.num_clusters} 个组`)
    await loadRuns()
  } catch {
    // error handled by interceptor
  } finally {
    detailLoading.value = false
  }
}

async function handleMoveAccount(username: string, targetClusterId: number) {
  if (!selectedRun.value) return
  try {
    await clusteringApi.moveAccount(selectedRun.value.id, username, {
      cluster_id: targetClusterId,
    })
    // 重新加载详情
    selectedRun.value = await clusteringApi.getRun(selectedRun.value.id)
    ElMessage.success(`已将 ${username} 移至组 ${targetClusterId}`)
  } catch {
    // error handled by interceptor
  }
}

async function handleDeleteRun(runId: number) {
  try {
    await ElMessageBox.confirm("确定要删除这次聚类运行吗？", "确认删除", {
      type: "warning",
    })
    await clusteringApi.deleteRun(runId)
    if (selectedRun.value?.id === runId) {
      selectedRun.value = null
    }
    ElMessage.success("已删除")
    await loadRuns()
  } catch {
    // cancelled or error
  }
}

// ── 生命周期 ──

onMounted(() => {
  loadRuns()
})
</script>

<template>
  <div class="clustering-view">
    <!-- 顶部操作栏 -->
    <el-card class="action-bar">
      <div class="action-row">
        <div class="action-params">
          <el-input-number
            v-model="minTweets"
            :min="1"
            :max="1000"
            size="small"
            controls-position="right"
          />
          <span class="param-label">最小推文数</span>

          <el-select v-model="linkageMethod" size="small" style="width: 120px">
            <el-option label="average" value="average" />
            <el-option label="complete" value="complete" />
            <el-option label="single" value="single" />
          </el-select>
          <span class="param-label">链接方法</span>
        </div>

        <el-button type="primary" :loading="runLoading" @click="handleRunClustering">
          运行聚类
        </el-button>
      </div>
    </el-card>

    <!-- 运行历史 -->
    <el-card class="runs-card">
      <template #header>
        <span>运行历史</span>
      </template>
      <el-table
        :data="runs"
        v-loading="loading"
        highlight-current-row
        @row-click="selectRun"
        style="width: 100%"
        size="small"
      >
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="num_clusters" label="组数" width="60" />
        <el-table-column prop="num_accounts" label="账号数" width="70" />
        <el-table-column prop="num_excluded" label="排除" width="60" />
        <el-table-column label="创建时间" width="160">
          <template #default="{ row }">{{ formatDatetime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="完成时间" width="160">
          <template #default="{ row }">{{ formatDatetime(row.completed_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button text type="danger" size="small" @click.stop="handleDeleteRun(row.id)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 聚类结果面板 -->
    <el-card v-if="selectedRun" v-loading="detailLoading" class="result-card">
      <template #header>
        <div class="result-header">
          <span>聚类结果 #{{ selectedRun.id }}</span>
          <div class="recut-controls">
            <el-radio-group v-model="recutMode" size="small">
              <el-radio-button value="height">按高度</el-radio-button>
              <el-radio-button value="clusters">按组数</el-radio-button>
            </el-radio-group>
            <el-input-number
              v-if="recutMode === 'height'"
              v-model="recutHeight"
              :min="0"
              :max="1"
              :step="0.05"
              :precision="3"
              size="small"
              controls-position="right"
              style="width: 120px"
            />
            <el-input-number
              v-else
              v-model="recutClusters"
              :min="2"
              :max="50"
              size="small"
              controls-position="right"
              style="width: 100px"
            />
            <el-button size="small" @click="handleReCut">应用</el-button>
          </div>
        </div>
      </template>

      <!-- 聚类组 -->
      <el-collapse>
        <el-collapse-item
          v-for="group in clusterGroups"
          :key="group.clusterId"
          :name="group.clusterId"
        >
          <template #title>
            <div class="group-title">
              <el-tag size="small">组 {{ group.clusterId }}</el-tag>
              <span class="group-info">
                {{ group.members.length }} 个账号 · {{ group.totalTweets }} 条推文
              </span>
            </div>
          </template>

          <!-- 组的 24 小时分布柱状图（centroid 均值） -->
          <div class="distribution-section">
            <div class="distribution-label">组平均分布</div>
            <div class="bar-chart">
              <div
                v-for="(val, hour) in group.centroid"
                :key="hour"
                class="bar-wrapper"
              >
                <div
                  class="bar centroid-bar"
                  :style="{
                    height: `${Math.max(val / Math.max(...group.centroid) * 80, 1)}px`,
                  }"
                  :title="`${hour}:00 - ${(val * 100).toFixed(1)}%`"
                />
                <span class="bar-label">{{ hour }}</span>
              </div>
            </div>
          </div>

          <!-- 账号列表 -->
          <el-table :data="group.members" size="small" style="margin-top: 12px">
            <el-table-column prop="username" label="账号" width="150" />
            <el-table-column prop="tweet_count" label="推文数" width="80" />
            <el-table-column label="手动调整" width="80">
              <template #default="{ row }">
                <el-tag v-if="row.is_manual_override" type="warning" size="small">手动</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="24h 分布" min-width="300">
              <template #default="{ row }">
                <div class="bar-chart bar-chart-small">
                  <div
                    v-for="(val, hour) in row.hourly_distribution"
                    :key="hour"
                    class="bar-wrapper-small"
                  >
                    <div
                      class="bar account-bar"
                      :style="{
                        height: `${Math.max(val / Math.max(...row.hourly_distribution) * 30, 1)}px`,
                      }"
                      :title="`${hour}:00 - ${(val * 100).toFixed(1)}%`"
                    />
                  </div>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="移动到" width="120">
              <template #default="{ row }">
                <el-select
                  :model-value="row.cluster_id"
                  size="small"
                  placeholder="移至..."
                  @change="(val: number) => handleMoveAccount(row.username, val)"
                >
                  <el-option
                    v-for="cid in availableClusterIds"
                    :key="cid"
                    :label="`组 ${cid}`"
                    :value="cid"
                    :disabled="cid === row.cluster_id"
                  />
                </el-select>
              </template>
            </el-table-column>
          </el-table>
        </el-collapse-item>
      </el-collapse>
    </el-card>
  </div>
</template>

<style scoped>
.clustering-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.action-bar {
  margin-bottom: 0;
}

.action-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.action-params {
  display: flex;
  align-items: center;
  gap: 8px;
}

.param-label {
  font-size: 13px;
  color: #606266;
  margin-right: 12px;
}

.runs-card {
  margin-bottom: 0;
}

.result-card {
  margin-bottom: 0;
}

.result-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}

.recut-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.group-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.group-info {
  font-size: 13px;
  color: #909399;
}

.distribution-section {
  padding: 8px 0;
}

.distribution-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
}

.bar-chart {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 100px;
  padding: 0 4px;
}

.bar-chart-small {
  height: 40px;
  gap: 1px;
  padding: 0;
}

.bar-wrapper {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1;
}

.bar-wrapper-small {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1;
}

.bar {
  width: 100%;
  min-width: 4px;
  border-radius: 2px 2px 0 0;
  transition: height 0.3s;
}

.centroid-bar {
  background: #409eff;
}

.account-bar {
  background: #67c23a;
}

.bar-label {
  font-size: 10px;
  color: #c0c4cc;
  margin-top: 2px;
}
</style>
