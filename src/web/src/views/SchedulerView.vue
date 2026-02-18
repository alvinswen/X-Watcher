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

          <!-- 3. 最早推文 -->
          <el-table-column label="最早推文" width="150" align="center">
            <template #default="{ row }">
              <el-tooltip
                v-if="tweetTimeRange[row.username]?.earliest_tweet_at"
                :content="formatFullDateTime(tweetTimeRange[row.username]!.earliest_tweet_at)"
                placement="top"
              >
                <span>{{ formatRelativeTime(tweetTimeRange[row.username]!.earliest_tweet_at) }}</span>
              </el-tooltip>
              <span v-else class="no-data">暂无</span>
            </template>
          </el-table-column>

          <!-- 4. 最近推文 -->
          <el-table-column label="最近推文" width="150" align="center">
            <template #default="{ row }">
              <el-tooltip
                v-if="tweetTimeRange[row.username]?.latest_tweet_at"
                :content="formatFullDateTime(tweetTimeRange[row.username]!.latest_tweet_at)"
                placement="top"
              >
                <span>{{ formatRelativeTime(tweetTimeRange[row.username]!.latest_tweet_at) }}</span>
              </el-tooltip>
              <span v-else class="no-data">暂无</span>
            </template>
          </el-table-column>

          <!-- 5. 推文总数 -->
          <el-table-column label="推文总数" width="100" align="center">
            <template #default="{ row }">
              {{ tweetTimeRange[row.username]?.tweet_count ?? '-' }}
            </template>
          </el-table-column>

          <!-- 6. 单次抓取数量 -->
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

      <!-- 手动定向抓取 -->
      <el-card class="section-card">
        <template #header>
          <span>手动定向抓取</span>
        </template>
        <div class="manual-scrape-section">
          <div class="manual-scrape-form">
            <el-select
              v-model="scrapeUsername"
              placeholder="选择账号"
              filterable
              style="width: 200px"
            >
              <el-option
                v-for="f in follows"
                :key="f.username"
                :label="'@' + f.username"
                :value="f.username"
              />
            </el-select>
            <el-input-number
              v-model="scrapeLimit"
              :min="1"
              :max="1000"
              :step="10"
              controls-position="right"
              style="width: 140px"
            />
            <el-button
              type="primary"
              :loading="scrapeSubmitting"
              :disabled="!scrapeUsername || !!scrapeTaskId"
              @click="handleStartScrape"
            >
              开始抓取
            </el-button>
          </div>

          <!-- 任务状态展示 -->
          <div v-if="scrapeTaskStatus" class="scrape-task-status">
            <el-descriptions :column="3" border size="small">
              <el-descriptions-item label="任务 ID">
                {{ scrapeTaskStatus.task_id.slice(0, 8) }}...
              </el-descriptions-item>
              <el-descriptions-item label="状态">
                <el-tag :type="scrapeStatusTagType" size="small">
                  {{ scrapeStatusText }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="进度">
                {{ scrapeTaskStatus.progress.current }} / {{ scrapeTaskStatus.progress.total }}
                ({{ scrapeTaskStatus.progress.percentage.toFixed(0) }}%)
              </el-descriptions-item>
            </el-descriptions>

            <div v-if="scrapeTaskStatus.status === 'completed'" class="scrape-result success">
              抓取完成。
              <span v-if="scrapeTaskStatus.result">
                新增 {{ scrapeTaskStatus.result.total_new ?? scrapeTaskStatus.result.success_count ?? 0 }} 条，
                跳过 {{ scrapeTaskStatus.result.total_skipped ?? scrapeTaskStatus.result.skipped_count ?? 0 }} 条。
              </span>
              <el-button link type="primary" size="small" @click="clearScrapeTask">清除</el-button>
            </div>
            <div v-if="scrapeTaskStatus.status === 'failed'" class="scrape-result error">
              抓取失败：{{ scrapeTaskStatus.error }}
              <el-button link type="primary" size="small" @click="clearScrapeTask">清除</el-button>
            </div>
          </div>
        </div>
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
import { ref, computed, onMounted, onUnmounted } from "vue"
import { ElMessage } from "element-plus"
import { schedulerApi, followsApi, tasksApi } from "@/api"
import { formatDuration, formatFullDateTime, formatRelativeTime } from "@/utils/format"
import type {
  ScheduleConfig,
  ScrapingFollow,
  FetchAnalysisResponse,
  FollowStats,
  TweetTimeRange,
  TaskStatusResponse,
} from "@/types"

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

// ==================== 推文时间范围状态 ====================

/** 账号推文时间范围（按 username 索引） */
const tweetTimeRange = ref<Record<string, TweetTimeRange>>({})

// ==================== 手动抓取状态 ====================

/** 手动抓取目标账号 */
const scrapeUsername = ref("")

/** 手动抓取数量 */
const scrapeLimit = ref(100)

/** 手动抓取提交中 */
const scrapeSubmitting = ref(false)

/** 当前抓取任务 ID */
const scrapeTaskId = ref<string | null>(null)

/** 当前抓取任务状态 */
const scrapeTaskStatus = ref<TaskStatusResponse | null>(null)

/** 轮询定时器 */
let pollTimer: ReturnType<typeof setInterval> | null = null

/** 任务状态标签颜色 */
const scrapeStatusTagType = computed(() => {
  switch (scrapeTaskStatus.value?.status) {
    case "pending": return "info"
    case "running": return "warning"
    case "completed": return "success"
    case "failed": return "danger"
    default: return "info"
  }
})

/** 任务状态中文文本 */
const scrapeStatusText = computed(() => {
  switch (scrapeTaskStatus.value?.status) {
    case "pending": return "等待中"
    case "running": return "抓取中"
    case "completed": return "已完成"
    case "failed": return "失败"
    default: return "未知"
  }
})

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
  await Promise.all([loadFollows(), loadFollowsStats(), loadTweetTimeRange()])
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

// ==================== 推文时间范围方法 ====================

/** 加载账号推文时间范围 */
async function loadTweetTimeRange() {
  try {
    const list = await schedulerApi.getTweetTimeRange()
    const map: Record<string, TweetTimeRange> = {}
    for (const item of list) {
      map[item.username] = item
    }
    tweetTimeRange.value = map
  } catch (error) {
    console.error("加载推文时间范围失败:", error)
  }
}

// ==================== 手动抓取方法 ====================

/** 触发手动抓取 */
async function handleStartScrape() {
  if (!scrapeUsername.value) return
  scrapeSubmitting.value = true
  try {
    const resp = await tasksApi.triggerScraping({
      usernames: scrapeUsername.value,
      limit: scrapeLimit.value,
    })
    scrapeTaskId.value = resp.task_id
    scrapeTaskStatus.value = null
    ElMessage.success("抓取任务已提交")
    startPolling()
  } catch (error) {
    console.error("提交抓取任务失败:", error)
  } finally {
    scrapeSubmitting.value = false
  }
}

/** 开始轮询任务状态 */
function startPolling() {
  stopPolling()
  pollTaskStatus()
  pollTimer = setInterval(pollTaskStatus, 3000)
}

/** 停止轮询 */
function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

/** 轮询查询任务状态 */
async function pollTaskStatus() {
  if (!scrapeTaskId.value) {
    stopPolling()
    return
  }
  try {
    const taskStatus = await tasksApi.getStatus(scrapeTaskId.value)
    scrapeTaskStatus.value = taskStatus
    if (taskStatus.status === "completed" || taskStatus.status === "failed") {
      stopPolling()
      if (taskStatus.status === "completed") {
        await loadTweetTimeRange()
      }
    }
  } catch (error) {
    console.error("查询任务状态失败:", error)
    stopPolling()
  }
}

/** 清除当前任务状态 */
function clearScrapeTask() {
  scrapeTaskId.value = null
  scrapeTaskStatus.value = null
  stopPolling()
}

// ==================== 初始化 ====================

onMounted(() => {
  loadConfig()
  loadFollows()
  loadFollowsStats()
  loadTweetTimeRange()
})

onUnmounted(() => {
  stopPolling()
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

.no-data {
  color: var(--el-text-color-placeholder);
  font-size: 12px;
}

.manual-scrape-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.manual-scrape-form {
  display: flex;
  align-items: center;
  gap: 12px;
}

.scrape-task-status {
  margin-top: 4px;
}

.scrape-result {
  margin-top: 8px;
  font-size: 14px;
}

.scrape-result.success {
  color: var(--el-color-success);
}

.scrape-result.error {
  color: var(--el-color-danger);
}
</style>
