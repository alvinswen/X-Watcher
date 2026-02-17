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
            <el-button link @click="loadFollows">刷新</el-button>
          </div>
        </template>
        <el-skeleton v-if="followsLoading" :rows="4" animated />
        <el-table v-else :data="follows" stripe border style="width: 100%">
          <el-table-column prop="username" label="账号" width="160">
            <template #default="{ row }">
              @{{ row.username }}
            </template>
          </el-table-column>
          <el-table-column label="推文数量" width="180">
            <template #default="{ row }">
              <el-tag v-if="row.manual_limit" type="warning" size="small">
                手动: {{ row.manual_limit }}
              </el-tag>
              <el-tag v-else type="info" size="small">
                自动计算
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="160">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openLimitDialog(row)">
                设置
              </el-button>
              <el-button link type="primary" size="small" @click="openAnalysisDialog(row)">
                分析
              </el-button>
            </template>
          </el-table-column>
          <el-table-column prop="reason" label="添加理由" show-overflow-tooltip />
        </el-table>
      </el-card>
    </template>

    <!-- 推文数量设置弹窗 -->
    <el-dialog v-model="limitDialogVisible" title="设置推文数量" width="420px">
      <el-form label-width="100px">
        <el-form-item label="账号">
          <span>@{{ editingFollow?.username }}</span>
        </el-form-item>
        <el-form-item label="数量模式">
          <el-radio-group v-model="limitMode">
            <el-radio value="auto">自动计算</el-radio>
            <el-radio value="manual">手动设置</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="limitMode === 'manual'" label="推文数量">
          <el-input-number
            v-model="manualLimitValue"
            :min="1"
            :max="1000"
            :step="10"
            controls-position="right"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="limitDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="updatingLimit" @click="handleSaveLimit">
          保存
        </el-button>
      </template>
    </el-dialog>

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
import type { ScheduleConfig, ScrapingFollow, FetchAnalysisResponse } from "@/types"

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

/** 设置弹窗可见性 */
const limitDialogVisible = ref(false)

/** 正在编辑的账号 */
const editingFollow = ref<ScrapingFollow | null>(null)

/** 数量模式 */
const limitMode = ref<"auto" | "manual">("auto")

/** 手动数量值 */
const manualLimitValue = ref(100)

/** 保存 limit 状态 */
const updatingLimit = ref(false)

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

/** 打开 limit 设置弹窗 */
function openLimitDialog(follow: ScrapingFollow) {
  editingFollow.value = follow
  if (follow.manual_limit) {
    limitMode.value = "manual"
    manualLimitValue.value = follow.manual_limit
  } else {
    limitMode.value = "auto"
    manualLimitValue.value = 100
  }
  limitDialogVisible.value = true
}

/** 保存 limit 设置 */
async function handleSaveLimit() {
  if (!editingFollow.value) return
  updatingLimit.value = true
  try {
    const manualLimit = limitMode.value === "manual" ? manualLimitValue.value : 0
    await followsApi.update(editingFollow.value.username, {
      manual_limit: manualLimit,
    })
    ElMessage.success(
      limitMode.value === "manual"
        ? `已设置 @${editingFollow.value.username} 手动抓取 ${manualLimitValue.value} 条`
        : `已恢复 @${editingFollow.value.username} 自动计算`,
    )
    limitDialogVisible.value = false
    await loadFollows()
  } catch (error) {
    console.error("保存 limit 失败:", error)
  } finally {
    updatingLimit.value = false
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
