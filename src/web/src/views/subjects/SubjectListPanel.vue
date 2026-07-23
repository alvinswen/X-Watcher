<script setup lang="ts">
import { Delete, Plus, VideoPause, VideoPlay } from "@element-plus/icons-vue"
import type { Subject, SubjectStatus } from "@/types"

defineProps<{
  subjects: Subject[]
  filteredSubjects: Subject[]
  selectedId: string | null
  activeCount: number
  activeLimitReached: boolean
  loading: boolean
  statusFilter: "all" | SubjectStatus
  formatRelative: (value?: string | null) => string
}>()

defineEmits<{
  "update:statusFilter": [value: "all" | SubjectStatus]
  create: []
  select: [subject: Subject]
  toggle: [subject: Subject]
  delete: [subject: Subject]
}>()
</script>

<template>
  <aside class="subjects-master">
    <div class="master-head">
      <div class="head-row">
        <h2>议题</h2>
        <span class="count-badge">活跃 {{ activeCount }}/20</span>
        <el-tooltip
          content="已达20活跃议题上限，请先停用旧议题"
          :disabled="!activeLimitReached"
          placement="bottom"
        >
          <span>
            <el-button
              type="primary"
              size="small"
              :icon="Plus"
              :disabled="activeLimitReached"
              data-testid="subjects-create"
              @click="$emit('create')"
            >
              新建
            </el-button>
          </span>
        </el-tooltip>
      </div>

      <el-radio-group
        :model-value="statusFilter"
        size="small"
        class="status-filter"
        data-testid="subjects-status-filter"
        @update:model-value="$emit('update:statusFilter', $event)"
      >
        <el-radio-button label="all" data-status-filter-option="all">全部</el-radio-button>
        <el-radio-button label="active" data-status-filter-option="active">活跃</el-radio-button>
        <el-radio-button label="paused" data-status-filter-option="paused">暂停</el-radio-button>
      </el-radio-group>
    </div>

    <div class="master-list" data-testid="subjects-list">
      <el-alert
        v-if="activeLimitReached"
        type="warning"
        :closable="false"
        show-icon
        class="limit-alert"
      >
        已达议题上限，先停用旧议题
      </el-alert>

      <template v-if="loading">
        <el-skeleton v-for="idx in 6" :key="idx" animated class="subject-skeleton">
          <template #template>
            <el-skeleton-item variant="text" class="sk-name" />
            <el-skeleton-item variant="text" class="sk-meta" />
          </template>
        </el-skeleton>
      </template>

      <el-empty
        v-else-if="subjects.length === 0"
        description="还没有议题，去创建"
        data-empty-state="first"
        class="empty-state"
      >
        <el-button type="primary" :icon="Plus" @click="$emit('create')">
          新建议题
        </el-button>
      </el-empty>

      <el-empty
        v-else-if="filteredSubjects.length === 0"
        description="当前过滤无结果，调整过滤"
        data-empty-state="filtered"
        class="empty-state"
      />

      <template v-else>
        <button
          v-for="subject in filteredSubjects"
          :key="subject.subject_id"
          class="subject-item"
          :class="{ selected: subject.subject_id === selectedId }"
          :data-subject-id="subject.subject_id"
          :data-status="subject.status"
          :data-selected="subject.subject_id === selectedId ? 'true' : undefined"
          @click="$emit('select', subject)"
        >
          <span class="item-line">
            <span class="subject-name" :title="subject.name">{{ subject.name }}</span>
            <span v-if="subject.status === 'paused'" data-paused-tag class="paused-tag">
              暂停
            </span>
          </span>
          <span class="item-meta">
            {{ formatRelative(subject.last_updated_at || subject.updated_at) }}
          </span>
          <span class="row-actions">
            <el-button
              text
              size="small"
              :icon="subject.status === 'active' ? VideoPause : VideoPlay"
              @click.stop="$emit('toggle', subject)"
            >
              {{ subject.status === "active" ? "暂停" : "恢复" }}
            </el-button>
            <el-button
              text
              size="small"
              type="danger"
              :icon="Delete"
              @click.stop="$emit('delete', subject)"
            >
              删除
            </el-button>
          </span>
        </button>
      </template>
    </div>
  </aside>
</template>

<style scoped>
.subjects-master {
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg-card);
  border-right: 1px solid var(--border-light);
}

.master-head {
  padding: 16px 16px 12px;
  border-bottom: 1px solid var(--border-light);
}

.head-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.head-row h2 {
  flex: 1;
  margin: 0;
  font-size: var(--summary-font-size);
  font-weight: 600;
}

.count-badge,
.item-meta {
  font-family: var(--font-mono);
  font-size: var(--xs-font-size);
  color: var(--text-tertiary);
}

.status-filter {
  width: 100%;
}

.status-filter :deep(.el-radio-button) {
  flex: 1;
}

.status-filter :deep(.el-radio-button__inner) {
  width: 100%;
}

.master-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 8px;
}

.limit-alert {
  margin-bottom: 8px;
}

.subject-skeleton {
  padding: 10px 12px;
}

.sk-name {
  width: 70%;
}

.sk-meta {
  width: 40%;
  margin-top: 6px;
}

.subject-item {
  position: relative;
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 10px 12px 10px 14px;
  margin-bottom: 2px;
  text-align: left;
  cursor: pointer;
  background: transparent;
  color: var(--text-primary);
  border: 0;
  border-left: 3px solid transparent;
  border-radius: var(--el-border-radius-base);
  font-family: var(--font-ui);
  transition: background var(--transition-base);
}

.subject-item:hover,
.subject-item.selected {
  background: var(--bg-inset);
}

.subject-item.selected {
  border-left-color: var(--color-primary);
}

.item-line {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.subject-name {
  flex: 1;
  min-width: 0;
  overflow-wrap: anywhere;
  font-size: var(--body-font-size);
  font-weight: 500;
}

.subject-item.selected .subject-name {
  color: var(--color-primary);
}

.paused-tag {
  flex-shrink: 0;
  padding: 0 6px;
  border: 1px solid var(--color-info);
  border-radius: var(--el-border-radius-small);
  color: var(--color-info);
  background: var(--bg-inset);
  font-size: var(--label-font-size);
  line-height: 16px;
}

.row-actions {
  position: absolute;
  right: 8px;
  top: 50%;
  display: flex;
  gap: 2px;
  opacity: 0;
  pointer-events: none;
  transform: translateY(-50%);
  background: var(--bg-inset);
  transition: opacity var(--transition-base);
}

.subject-item:hover .row-actions,
.subject-item:focus-within .row-actions {
  opacity: 1;
  pointer-events: auto;
}

.empty-state {
  padding: 40px 16px;
}
</style>
