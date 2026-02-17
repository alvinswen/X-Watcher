<template>
  <div class="scheduler-view">
    <el-skeleton v-if="loading" :rows="6" animated />

    <template v-else-if="config">
      <!-- 抓取调度状态 -->
      <el-card class="section-card">
        <template #header>
          <div class="card-header">
            <span>抓取调度状态</span>
            <el-button link @click="loadConfig">刷新</el-button>
          </div>
        </template>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="启用状态">
            <el-switch
              :model-value="config.is_enabled"
              :loading="toggling"
              active-text="启用"
              inactive-text="禁用"
              @change="handleToggleEnabled"
            />
          </el-descriptions-item>
          <el-descriptions-item label="调度器运行">
            <el-tag :type="config.scheduler_running ? 'success' : 'info'" size="small">
              {{ config.scheduler_running ? '运行中' : '未运行' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="抓取间隔">
            {{ formatDuration(config.interval_seconds) }}
          </el-descriptions-item>
          <el-descriptions-item label="下次执行时间">
            {{ formatFullDateTime(config.next_run_time) }}
          </el-descriptions-item>
          <el-descriptions-item label="最后更新时间">
            {{ formatFullDateTime(config.updated_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="最后更新人">
            {{ config.updated_by || '-' }}
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- 间隔设置 -->
      <el-card class="section-card">
        <template #header>
          <span>抓取间隔设置</span>
        </template>
        <div class="interval-section">
          <div class="interval-presets">
            <el-radio-group v-model="selectedInterval" @change="handlePresetChange">
              <el-radio-button :value="1800">30 分钟</el-radio-button>
              <el-radio-button :value="3600">1 小时</el-radio-button>
              <el-radio-button :value="7200">2 小时</el-radio-button>
              <el-radio-button :value="14400">4 小时</el-radio-button>
              <el-radio-button :value="28800">8 小时</el-radio-button>
              <el-radio-button :value="86400">24 小时</el-radio-button>
            </el-radio-group>
          </div>
          <div class="interval-custom">
            <span class="custom-label">自定义（秒）:</span>
            <el-input-number
              v-model="customInterval"
              :min="300"
              :max="604800"
              :step="300"
              controls-position="right"
              @change="handleCustomIntervalChange"
            />
            <el-button
              type="primary"
              :loading="updatingInterval"
              @click="handleUpdateInterval"
            >
              更新间隔
            </el-button>
          </div>
        </div>
      </el-card>

      <!-- 下次执行时间设置 -->
      <el-card class="section-card">
        <template #header>
          <span>下次执行时间</span>
        </template>
        <div class="next-run-section">
          <el-date-picker
            v-model="nextRunTime"
            type="datetime"
            placeholder="选择下次执行时间"
            :disabled-date="disablePastDate"
            format="YYYY-MM-DD HH:mm:ss"
            value-format="YYYY-MM-DDTHH:mm:ss"
          />
          <el-button
            type="primary"
            :loading="updatingNextRun"
            :disabled="!nextRunTime"
            @click="handleUpdateNextRun"
          >
            设置执行时间
          </el-button>
        </div>
      </el-card>

      <!-- 抓取账号配置 -->
      <el-card class="section-card">
        <template #header>
          <div class="card-header">
            <span>抓取账号配置</span>
            <el-button link @click="refreshFollows">刷新</el-button>
          </div>
        </template>
        <el-skeleton v-if="followsLoading" :rows="4" animated />
        <el-table v-else :data="follows" stripe border style="width: 100%">
          <!-- 1. 账号 -->
          <el-table-column prop="username" label="账号" width="160">
            <template #default="{ row }">
              @{{ row.username }}
            </template>
          </el-table-column>

          <!-- 2. 添加理由 -->
          <el-table-column prop="reason" label="添加理由" show-overflow-tooltip />

          <!-- 3. 单次抓取数量 -->
          <el-table-column label="单次抓取数量" width="140" align="center">
            <template #default="{ row }">
              <!-- 手动模式：可编辑 input -->
              <el-input-number
                v-if="row.manual_limit"
                v-model="row.manual_limit"
                :min="1"
                :max="1000"
                size="small"
                controls-position="right"
                style="width: 110px"
                @blur="handleLimitBlur(row)"
              />
              <!-- 自动模式：只读显示 effective_limit -->
              <span v-else class="auto-limit">
                {{ followsStats[row.username]?.effective_limit ?? '-' }}
              </span>
            </template>
          </el-table-column>

          <!-- 4. 计算策略 -->
          <el-table-column label="计算策略" width="130" align="center">
            <template #default="{ row }">
              <el-select
                :model-value="row.manual_limit ? 'manual' : 'auto'"
                size="small"
                style="width: 110px"
                @change="(v: string) => handleStrategyChange(row, v)"
              >
                <el-option label="自动计算" value="auto" />
                <el-option label="手动设置" value="manual" />
              </el-select>
            </template>
          </el-table-column>

          <!-- 5. 近期最大值/12h -->
          <el-table-column label="近期最大值/12h" width="140" align="center">
            <template #default="{ row }">
              {{ followsStats[row.username]?.max_count_12h ?? '-' }}
            </template>
          </el-table-column>

          <!-- 6. 近期最大值/24h -->
          <el-table-column label="近期最大值/24h" width="140" align="center">
            <template #default="{ row }">
              {{ followsStats[row.username]?.max_count_24h ?? '-' }}
            </template>
          </el-table-column>

          <!-- 7. 分析 -->
          <el-table-column label="分析" width="80" align="center">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openAnalysisDialog(row)">
                详细
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </template>

    <!-- 抓取分析弹窗 -->
    <el-dialog v-model="analysisDialogVisible" title="抓取结果分析" width="700px">
      <div class="analysis-header">
        <span class="analysis-username">@{{ analysisUsername }}</span>
        <el-radio-group v-model="analysisInterval" size="small" @change="loadAnalysis">
          <el-radio-button :value="12">12 小时</el-radio-button>
          <el-radio-button :value="24">24 小时</el-radio-button>
        </el-radio-group>
      </div>

      <el-skeleton v-if="analysisLoading" :rows="10" animated />

      <template v-else-if="analysisData">
        <div class="analysis-summary">
          过去 {{ analysisData.periods.length }} 个周期共
          <strong>{{ analysisData.total_new_tweets }}</strong> 条新推文
        </div>
        <el-table :data="analysisData.periods" stripe border style="width: 100%">
          <el-table-column label="周期" min-width="240">
            <template #default="{ row }">
              {{ formatShortDateTime(row.period_start) }} ~ {{ formatShortDateTime(row.period_end) }}
            </template>
          </el-table-column>
          <el-table-column label="新推文数" width="120" align="center">
            <template #default="{ row }">
              <span :class="{ 'count-zero': row.new_tweet_count === 0 }">
                {{ row.new_tweet_count }}
              </span>
            </template>
          </el-table-column>
        </el-table>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from "vue"
import { ElMessage } from "element-plus"
import { schedulerApi, followsApi } from "@/api"
import { formatDuration, formatFullDateTime } from "@/utils/format"
import type { ScheduleConfig, ScrapingFollow, FetchAnalysisResponse, FollowStats } from "@/types"

// ==================== 调度配置状态 ====================

/** 调度器配置 */
const config = ref<ScheduleConfig | null>(null)

/** 加载状态 */
const loading = ref(true)

/** 启用/禁用切换状态 */
const toggling = ref(false)

/** 间隔更新状态 */
const updatingInterval = ref(false)

/** 下次执行时间更新状态 */
const updatingNextRun = ref(false)

/** 预设间隔选中值 */
const selectedInterval = ref<number | undefined>(undefined)

/** 自定义间隔值 */
const customInterval = ref(3600)

/** 下次执行时间 */
const nextRunTime = ref("")

/** 预设间隔值列表 */
const presetValues = [1800, 3600, 7200, 14400, 28800, 86400]

// ==================== 账号配置状态 ====================

/** 账号列表 */
const follows = ref<ScrapingFollow[]>([])

/** 账号加载状态 */
const followsLoading = ref(false)

/** 账号运行时统计（按 username 索引） */
const followsStats = ref<Record<string, FollowStats>>({})

// ==================== 分析弹窗状态 ====================

/** 分析弹窗可见性 */
const analysisDialogVisible = ref(false)

/** 分析的用户名 */
const analysisUsername = ref("")

/** 分析间隔 */
const analysisInterval = ref(12)

/** 分析数据 */
const analysisData = ref<FetchAnalysisResponse | null>(null)

/** 分析加载状态 */
const analysisLoading = ref(false)

// ==================== 调度配置方法 ====================

/** 加载调度器配置 */
async function loadConfig() {
  loading.value = true
  try {
    config.value = await schedulerApi.getConfig()
    // 同步当前间隔到 UI
    const current = config.value.interval_seconds
    customInterval.value = current
    selectedInterval.value = presetValues.includes(current) ? current : undefined
  } catch (error) {
    console.error("加载调度器配置失败:", error)
  } finally {
    loading.value = false
  }
}

/** 切换启用/禁用 */
async function handleToggleEnabled(value: boolean | string | number) {
  toggling.value = true
  try {
    if (value) {
      config.value = await schedulerApi.enable()
      ElMessage.success("抓取调度已启用")
    } else {
      config.value = await schedulerApi.disable()
      ElMessage.success("抓取调度已禁用")
    }
  } catch (error) {
    console.error("切换调度器状态失败:", error)
  } finally {
    toggling.value = false
  }
}

/** 预设间隔选择变化 */
function handlePresetChange(value: number) {
  customInterval.value = value
}

/** 自定义间隔变化 */
function handleCustomIntervalChange(value: number | undefined) {
  if (value !== undefined) {
    selectedInterval.value = presetValues.includes(value) ? value : undefined
  }
}

/** 更新间隔 */
async function handleUpdateInterval() {
  updatingInterval.value = true
  try {
    config.value = await schedulerApi.updateInterval({
      interval_seconds: customInterval.value,
    })
    ElMessage.success("抓取间隔已更新")
    // 同步预设选中
    selectedInterval.value = presetValues.includes(customInterval.value)
      ? customInterval.value
      : undefined
  } catch (error) {
    console.error("更新间隔失败:", error)
  } finally {
    updatingInterval.value = false
  }
}

/** 禁用过去日期 */
function disablePastDate(date: Date): boolean {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return date.getTime() < today.getTime()
}

/** 更新下次执行时间 */
async function handleUpdateNextRun() {
  if (!nextRunTime.value) return
  updatingNextRun.value = true
  try {
    // value-format 产出的是不带时区的本地时间字符串（如 "2026-02-14T22:50:00"），
    // 需要先构造为 Date（浏览器视为本地时间），再转 ISO 字符串（UTC + 'Z'）发送给后端
    const localDate = new Date(nextRunTime.value)
    config.value = await schedulerApi.updateNextRun({
      next_run_time: localDate.toISOString(),
    })
    ElMessage.success("下次执行时间已更新")
    nextRunTime.value = ""
  } catch (error) {
    console.error("更新下次执行时间失败:", error)
  } finally {
    updatingNextRun.value = false
  }
}

// ==================== 账号配置方法 ====================

/** 加载账号列表 */
async function loadFollows() {
  followsLoading.value = true
  try {
    follows.value = await followsApi.list()
  } catch (error) {
    console.error("加载账号列表失败:", error)
  } finally {
    followsLoading.value = false
  }
}

/** 加载账号运行时统计 */
async function loadFollowsStats() {
  try {
    const statsList = await schedulerApi.getFollowsStats()
    const map: Record<string, FollowStats> = {}
    for (const s of statsList) {
      map[s.username] = s
    }
    followsStats.value = map
  } catch (error) {
    console.error("加载账号统计失败:", error)
  }
}

/** 刷新账号列表和统计 */
async function refreshFollows() {
  await Promise.all([loadFollows(), loadFollowsStats()])
}

/** 计算策略切换 → 立即调 API */
async function handleStrategyChange(row: ScrapingFollow, strategy: string) {
  try {
    if (strategy === "manual") {
      // 切到手动，默认值 10
      await followsApi.update(row.username, { manual_limit: 10 })
      ElMessage.success(`已切换 @${row.username} 为手动设置（默认 10 条）`)
    } else {
      // 切到自动，清除手动值
      await followsApi.update(row.username, { manual_limit: 0 })
      ElMessage.success(`已恢复 @${row.username} 自动计算`)
    }
    await Promise.all([loadFollows(), loadFollowsStats()])
  } catch (error) {
    console.error("切换计算策略失败:", error)
  }
}

/** 手动 limit blur → 校验 + 立即保存 */
async function handleLimitBlur(row: ScrapingFollow) {
  const val = row.manual_limit
  if (val == null || val < 1 || val > 1000) {
    ElMessage.warning("抓取数量需在 1-1000 之间")
    await loadFollows() // 回滚到服务端值
    return
  }
  try {
    await followsApi.update(row.username, { manual_limit: val })
    ElMessage.success(`已设置 @${row.username} 单次抓取 ${val} 条`)
  } catch (error) {
    console.error("保存抓取数量失败:", error)
    await loadFollows() // 出错时回滚
  }
}

// ==================== 分析弹窗方法 ====================

/** 打开分析弹窗 */
function openAnalysisDialog(follow: ScrapingFollow) {
  analysisUsername.value = follow.username
  analysisInterval.value = 12
  analysisData.value = null
  analysisDialogVisible.value = true
  loadAnalysis()
}

/** 加载分析数据 */
async function loadAnalysis() {
  analysisLoading.value = true
  try {
    analysisData.value = await schedulerApi.getFollowAnalysis(
      analysisUsername.value,
      analysisInterval.value,
    )
  } catch (error) {
    console.error("加载分析数据失败:", error)
  } finally {
    analysisLoading.value = false
  }
}

/** 格式化短日期时间 */
function formatShortDateTime(dateStr: string): string {
  const date = new Date(dateStr)
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

// ==================== 初始化 ====================

onMounted(() => {
  loadConfig()
  loadFollows()
  loadFollowsStats()
})
</script>

<style scoped>
.scheduler-view {
  max-width: 1200px;
  margin: 0 auto;
}

.section-card {
  margin-bottom: 1.5rem;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.interval-section {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.interval-custom {
  display: flex;
  align-items: center;
  gap: 12px;
}

.custom-label {
  font-size: 14px;
  color: var(--el-text-color-regular);
  white-space: nowrap;
}

.next-run-section {
  display: flex;
  align-items: center;
  gap: 12px;
}

.auto-limit {
  color: var(--el-text-color-regular);
}

.analysis-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.analysis-username {
  font-size: 16px;
  font-weight: 500;
}

.analysis-summary {
  margin-bottom: 12px;
  color: var(--el-text-color-regular);
  font-size: 14px;
}

.count-zero {
  color: var(--el-text-color-placeholder);
}
</style>
