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
        <el-radio-button label="all">全部</el-radio-button>
        <el-radio-button label="active">活跃</el-radio-button>
        <el-radio-button label="paused">暂停</el-radio-button>
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
