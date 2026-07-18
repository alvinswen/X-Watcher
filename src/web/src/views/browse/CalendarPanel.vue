<script setup lang="ts">
import { computed } from "vue"

const props = defineProps<{
  modelValue: Date
  dailyCounts: Record<string, number>
}>()

const emit = defineEmits<{
  "update:modelValue": [value: Date]
}>()

const selectedDate = computed({
  get: () => props.modelValue,
  set: (value: Date) => emit("update:modelValue", value),
})

function getDayCount(day: string): number {
  return props.dailyCounts[day] || 0
}
</script>

<template>
  <div class="calendar-panel">
    <el-calendar v-model="selectedDate" class="browse-calendar">
      <template #date-cell="{ data }">
        <div class="calendar-cell" :class="{ 'has-tweets': getDayCount(data.day) > 0 }">
          <span class="calendar-day">{{ data.day.split("-").slice(2).join("") }}</span>
          <span v-if="getDayCount(data.day) > 0" class="tweet-count">
            {{ getDayCount(data.day) }}
          </span>
        </div>
      </template>
    </el-calendar>
  </div>
</template>

<style scoped>
.calendar-panel {
  width: 320px;
  flex-shrink: 0;
  overflow-y: auto;
}

.browse-calendar {
  --el-calendar-border: 1px solid var(--border-light);
  background-color: var(--bg-card);
  border-radius: var(--card-radius);
}

.browse-calendar :deep(.el-calendar__header) {
  padding: 8px 12px;
  font-family: var(--font-reading);
}

.browse-calendar :deep(.el-calendar__body) {
  padding: 0 8px 8px;
}

.browse-calendar :deep(.el-calendar-table .el-calendar-day) {
  height: 48px;
  padding: 2px;
}

.calendar-cell {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.calendar-cell.has-tweets {
  font-weight: 600;
}

.calendar-day {
  font-size: 13px;
  font-family: var(--font-mono);
}

.tweet-count {
  color: var(--color-primary);
  font-size: var(--label-font-size);
  font-weight: 500;
  font-family: var(--font-mono);
  white-space: nowrap;
}

.calendar-cell .tweet-count {
  position: absolute;
  top: 0;
  right: 2px;
}
</style>
