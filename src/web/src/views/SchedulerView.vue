<template>
  <div class="scheduler-view">
    <el-skeleton v-if="loading" :rows="6" animated />

    <template v-else-if="config">
      <!-- 当前状态 -->
      <el-card class="section-card">
        <template #header>
          <div class="card-header">
            <span>调度器状态</span>
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
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from "vue"
import { ElMessage } from "element-plus"
import { schedulerApi } from "@/api"
import { formatDuration, formatFullDateTime } from "@/utils/format"
import type { ScheduleConfig } from "@/types"

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
      ElMessage.success("调度器已启用")
    } else {
      config.value = await schedulerApi.disable()
      ElMessage.success("调度器已禁用")
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

onMounted(() => {
  loadConfig()
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
</style>
