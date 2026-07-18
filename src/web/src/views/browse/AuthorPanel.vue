<script setup lang="ts">
import { User } from "@element-plus/icons-vue"
import type { AuthorInfo } from "@/types"

defineProps<{
  authors: AuthorInfo[]
  loading: boolean
  selectedAuthor: string | null
  totalTweets: number
}>()

defineEmits<{
  select: [username: string | null]
  timeline: [username: string]
}>()
</script>

<template>
  <div class="author-panel" data-testid="browse-author-panel">
    <div class="panel-header">作者列表</div>
    <el-skeleton v-if="loading" :rows="5" animated />
    <div v-else class="author-list">
      <div
        class="author-item"
        :class="{ active: selectedAuthor === null }"
        @click="$emit('select', null)"
      >
        <span class="author-name-text">全部作者</span>
        <span class="tweet-count">{{ totalTweets }}</span>
      </div>
      <div
        v-for="author in authors"
        :key="author.author_username"
        class="author-item"
        :class="{ active: selectedAuthor === author.author_username }"
        @click="$emit('select', author.author_username)"
      >
        <div class="author-info-block">
          <div class="author-name-row">
            <span class="author-display-name">
              {{ author.author_display_name || author.author_username }}
            </span>
            <el-button
              text
              size="small"
              class="timeline-btn"
              title="查看历史推文"
              @click.stop="$emit('timeline', author.author_username)"
            >
              <el-icon :size="12"><User /></el-icon>
            </el-button>
          </div>
          <span class="author-handle">@{{ author.author_username }}</span>
          <span v-if="author.reason" class="author-reason" :title="author.reason">
            {{ author.reason }}
          </span>
        </div>
        <div class="author-item-actions">
          <span class="tweet-count">{{ author.tweet_count }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.author-panel {
  width: 240px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--card-radius);
}

.panel-header {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-light);
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 600;
  font-family: var(--font-reading);
}

.author-list {
  flex: 1;
  overflow-y: auto;
}

.author-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  border-bottom: 1px solid var(--border-light);
  cursor: pointer;
  transition: background-color var(--transition-base);
}

.author-item:last-child {
  border-bottom: none;
}

.author-item:hover {
  background-color: var(--bg-inset);
}

.author-item.active {
  background-color: var(--color-primary-lighter);
  color: var(--color-primary);
}

.author-info-block {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  margin-right: 8px;
}

.author-name-row {
  display: flex;
  align-items: center;
  gap: 2px;
}

.author-display-name {
  overflow: hidden;
  color: var(--text-primary);
  font-size: var(--small-font-size);
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.author-handle,
.author-reason {
  overflow: hidden;
  font-size: var(--label-font-size);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.author-handle {
  color: var(--text-tertiary);
  font-family: var(--font-mono);
}

.author-reason {
  color: var(--text-secondary);
}

.author-name-text {
  color: var(--text-primary);
  font-size: var(--small-font-size);
  font-weight: 500;
}

.author-item-actions {
  display: flex;
  flex-shrink: 0;
  align-items: center;
  gap: 4px;
}

.tweet-count {
  color: var(--color-primary);
  font-size: var(--label-font-size);
  font-weight: 500;
  font-family: var(--font-mono);
  white-space: nowrap;
}

.timeline-btn {
  padding: 2px 4px;
  color: var(--text-tertiary);
  transition: color var(--transition-base);
}

.timeline-btn:hover {
  color: var(--color-primary);
}
</style>
