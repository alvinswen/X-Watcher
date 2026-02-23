<script setup lang="ts">
import { ref, computed, onMounted, shallowRef } from "vue"
import { use } from "echarts/core"
import { BarChart } from "echarts/charts"
import {
  TitleComponent,
  TooltipComponent,
  GridComponent,
  DataZoomComponent,
} from "echarts/components"
import { CanvasRenderer } from "echarts/renderers"
import VChart from "vue-echarts"
import type { TopicListItem } from "@/types/topic"
import type { PostingFrequencyResponse, FrequencySlot } from "@/types/analytics"
import { topicsApi } from "@/api/topics"
import { analyticsApi } from "@/api/analytics"
import { ElMessage } from "element-plus"

// 注册 ECharts 模块
use([
  BarChart,
  TitleComponent,
  TooltipComponent,
  GridComponent,
  DataZoomComponent,
  CanvasRenderer,
])

/** 主题列表 */
const topics = ref<TopicListItem[]>([])
const topicsLoading = ref(false)

/** 选中的主题 ID */
const selectedTopicId = ref<number | null>(null)

/** 时段数量 */
const slotsCount = ref(50)

/** 频次数据 */
const frequencyData = shallowRef<PostingFrequencyResponse | null>(null)
const chartLoading = ref(false)

/** 加载主题列表 */
async function loadTopics() {
  topicsLoading.value = true
  try {
    topics.value = await topicsApi.list()
  } catch {
    ElMessage.error("加载主题列表失败")
  } finally {
    topicsLoading.value = false
  }
}

/** 加载频次数据 */
async function loadFrequency() {
  if (!selectedTopicId.value) return

  chartLoading.value = true
  try {
    frequencyData.value = await analyticsApi.getPostingFrequency(
      selectedTopicId.value,
      {
        tz_offset: new Date().getTimezoneOffset(),
        slots: slotsCount.value,
      },
    )
  } catch {
    ElMessage.error("加载发文频次数据失败")
    frequencyData.value = null
  } finally {
    chartLoading.value = false
  }
}

/** 主题变更 */
function handleTopicChange() {
  loadFrequency()
}

/** 时段数量变更 */
function handleSlotsChange() {
  if (selectedTopicId.value) {
    loadFrequency()
  }
}

/**
 * 补全稀疏数据为完整的时段序列。
 * 后端返回稀疏表示（只包含有推文的时段），前端填充零值。
 */
const fullSlots = computed(() => {
  if (!frequencyData.value) return []

  const { time_range, slot_minutes, distribution } = frequencyData.value

  // 构建 slot → count 映射
  const countMap = new Map<string, number>()
  for (const d of distribution) {
    countMap.set(d.slot, d.count)
  }

  // 根据 time_range 生成完整时段序列
  const startMs = new Date(time_range.start).getTime()
  const endMs = new Date(time_range.end).getTime()
  const offsetMs = -new Date().getTimezoneOffset() * 60 * 1000 // 本地偏移
  const slotMs = slot_minutes * 60 * 1000

  // 对齐起始时间到 slot 边界
  const alignedStartMs = Math.floor((startMs + offsetMs) / slotMs) * slotMs - offsetMs

  const result: FrequencySlot[] = []
  for (let ms = alignedStartMs; ms < endMs; ms += slotMs) {
    const localDate = new Date(ms + offsetMs)
    const label =
      localDate.getFullYear() +
      "-" +
      String(localDate.getMonth() + 1).padStart(2, "0") +
      "-" +
      String(localDate.getDate()).padStart(2, "0") +
      " " +
      String(localDate.getHours()).padStart(2, "0") +
      ":" +
      String(localDate.getMinutes()).padStart(2, "0")

    result.push({
      slot: label,
      count: countMap.get(label) ?? 0,
    })
  }

  return result
})

/** ECharts 配置 */
const chartOption = computed(() => {
  const slots = fullSlots.value
  if (slots.length === 0) return {}

  // X 轴标签：只显示时间部分 (HH:MM)
  const xLabels = slots.map((s) => {
    const parts = s.slot.split(" ")
    return parts.length === 2 ? parts[1] : s.slot
  })
  const counts = slots.map((s) => s.count)
  const maxCount = Math.max(...counts, 1)

  return {
    tooltip: {
      trigger: "axis",
      formatter(params: any) {
        const p = Array.isArray(params) ? params[0] : params
        const idx = p.dataIndex
        const fullLabel = slots[idx]?.slot ?? ""
        return `<strong>${fullLabel}</strong><br/>发文数: ${p.value}`
      },
    },
    grid: {
      left: 50,
      right: 20,
      top: 20,
      bottom: 80,
    },
    dataZoom: [
      {
        type: "slider",
        show: slots.length > 30,
        start: slots.length > 30 ? Math.max(0, 100 - (30 / slots.length) * 100) : 0,
        end: 100,
        height: 20,
        bottom: 10,
      },
    ],
    xAxis: {
      type: "category",
      data: xLabels,
      axisLabel: {
        rotate: 45,
        fontSize: 11,
        interval: Math.max(0, Math.floor(slots.length / 20) - 1),
      },
    },
    yAxis: {
      type: "value",
      minInterval: 1,
      max: maxCount < 5 ? 5 : undefined,
    },
    series: [
      {
        type: "bar",
        data: counts,
        itemStyle: {
          color(params: any) {
            // 有推文的时段高亮
            return params.value > 0 ? "#409eff" : "#e8e8e8"
          },
          borderRadius: [2, 2, 0, 0],
        },
        barMaxWidth: 20,
      },
    ],
  }
})

/** 选中的主题名称 */
const selectedTopicName = computed(() => {
  if (!selectedTopicId.value) return ""
  return topics.value.find((t) => t.id === selectedTopicId.value)?.name ?? ""
})

onMounted(() => {
  loadTopics()
})
</script>

<template>
  <div class="analytics-view">
    <!-- 控制栏 -->
    <el-card shadow="never" class="control-card">
      <el-row :gutter="16" align="middle">
        <el-col :xs="24" :sm="10" :md="8">
          <div class="control-item">
            <span class="control-label">主题</span>
            <el-select
              v-model="selectedTopicId"
              placeholder="请选择主题"
              :loading="topicsLoading"
              filterable
              style="width: 100%"
              @change="handleTopicChange"
            >
              <el-option
                v-for="topic in topics"
                :key="topic.id"
                :label="`${topic.name} (${topic.account_count} 个账号)`"
                :value="topic.id"
              />
            </el-select>
          </div>
        </el-col>
        <el-col :xs="24" :sm="8" :md="6">
          <div class="control-item">
            <span class="control-label">时段数</span>
            <el-select
              v-model="slotsCount"
              style="width: 100%"
              @change="handleSlotsChange"
            >
              <el-option :label="'24 个 (12 小时)'" :value="24" />
              <el-option :label="'50 个 (25 小时)'" :value="50" />
              <el-option :label="'96 个 (2 天)'" :value="96" />
              <el-option :label="'336 个 (7 天)'" :value="336" />
            </el-select>
          </div>
        </el-col>
        <el-col :xs="24" :sm="6" :md="4">
          <el-button
            type="primary"
            :loading="chartLoading"
            :disabled="!selectedTopicId"
            @click="loadFrequency"
          >
            刷新
          </el-button>
        </el-col>
      </el-row>
    </el-card>

    <!-- 统计摘要 -->
    <el-row v-if="frequencyData" :gutter="16" class="stats-row">
      <el-col :xs="12" :sm="6">
        <el-card shadow="hover" class="stat-card">
          <el-statistic title="主题名称" :value="selectedTopicName" />
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="hover" class="stat-card">
          <el-statistic title="总发文数" :value="frequencyData.total_tweets" />
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="hover" class="stat-card">
          <el-statistic
            title="活跃时段"
            :value="frequencyData.distribution.length"
            :suffix="`/ ${fullSlots.length}`"
          />
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="hover" class="stat-card">
          <el-statistic title="时段粒度" :value="frequencyData.slot_minutes" suffix="分钟" />
        </el-card>
      </el-col>
    </el-row>

    <!-- 图表区域 -->
    <el-card shadow="never" class="chart-card">
      <template v-if="!selectedTopicId">
        <el-empty description="请先选择一个主题" />
      </template>
      <template v-else-if="chartLoading">
        <div class="chart-loading">
          <el-skeleton :rows="8" animated />
        </div>
      </template>
      <template v-else-if="frequencyData && frequencyData.total_tweets === 0">
        <el-empty description="该主题在选定时段内无发文数据" />
      </template>
      <template v-else-if="frequencyData">
        <v-chart
          :option="chartOption"
          style="height: 400px; width: 100%"
          autoresize
        />
      </template>
    </el-card>
  </div>
</template>

<style scoped>
.analytics-view {
  padding: 0;
}

.control-card {
  margin-bottom: 16px;
}

.control-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.control-label {
  font-size: 14px;
  color: #606266;
  white-space: nowrap;
  min-width: 50px;
}

.stats-row {
  margin-bottom: 16px;
}

.stat-card {
  text-align: center;
}

.chart-card {
  min-height: 300px;
}

.chart-loading {
  padding: 40px 20px;
}
</style>
