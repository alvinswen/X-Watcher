<script setup lang="ts">
import { ArrowLeft } from "@element-plus/icons-vue"
import type { AuthorInfo } from "@/types"

defineProps<{
  author: string | null
  authorInfo: Pick<AuthorInfo, "author_username" | "author_display_name" | "reason"> | null
  presets: Array<{ label: string; days: number | null }>
  activePreset: number | null | undefined
  dateRange: [Date, Date]
  total: number
}>()

defineEmits<{
  back: []
  preset: [days: number | null]
  "update:dateRange": [value: [Date, Date]]
  rangeChange: []
}>()
</script>

<template>
  <div class="timeline-sidebar">
    <div class="timeline-back">
      <el-button text @click="$emit('back')">
        <el-icon><ArrowLeft /></el-icon> 返回日期浏览
      </el-button>
    </div>

    <div class="timeline-author-card">
      <div class="timeline-author-name">{{ authorInfo?.author_display_name || author }}</div>
      <div class="timeline-author-handle">@{{ author }}</div>
      <div v-if="authorInfo?.reason" class="timeline-author-reason">
        {{ authorInfo.reason }}
      </div>
    </div>

    <div class="timeline-range-section">
      <div class="timeline-presets">
        <el-button
          v-for="preset in presets"
          :key="preset.days"
          size="small"
          :type="activePreset === preset.days ? 'primary' : 'default'"
          @click="$emit('preset', preset.days)"
        >
          {{ preset.label }}
        </el-button>
      </div>
      <el-date-picker
        :model-value="dateRange"
        type="daterange"
        range-separator="至"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        size="small"
        style="width: 100%; margin-top: 8px"
        @update:model-value="$emit('update:dateRange', $event)"
        @change="$emit('rangeChange')"
      />
    </div>

    <div class="timeline-stats">共 {{ total }} 条推文</div>
  </div>
</template>

<style scoped>
.timeline-sidebar {
  width: 320px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--card-radius);
}

.timeline-back {
  margin-bottom: 4px;
}

.timeline-author-card {
  padding: 16px;
  background: var(--bg-inset);
  border-radius: 6px;
}

.timeline-author-name {
  color: var(--text-primary);
  font-size: 16px;
  font-weight: 600;
  font-family: var(--font-reading);
}

.timeline-author-handle {
  margin-top: 2px;
  color: var(--text-tertiary);
  font-size: var(--small-font-size);
  font-family: var(--font-mono);
}

.timeline-author-reason {
  margin-top: 8px;
  color: var(--text-secondary);
  font-size: var(--small-font-size);
  line-height: 1.6;
  font-family: var(--font-reading);
}

.timeline-range-section {
  padding: 0;
}

.timeline-presets {
  display: flex;
  gap: 8px;
}

.timeline-stats {
  color: var(--text-tertiary);
  font-size: var(--small-font-size);
  font-family: var(--font-mono);
}
</style>
