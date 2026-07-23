<script setup lang="ts">
import type { Component } from "vue"
import { ChatLineSquare } from "@element-plus/icons-vue"
import type { SubjectFeedItem } from "@/types"
import { formatDateTime } from "./subjectFormat"

defineProps<{
  loading: boolean
  items: SubjectFeedItem[]
  hintState: "recent" | "stale" | "never" | "empty"
  lastClassifiedAt: string | null
  hintTitle: string
  hintIcon: Component
  hintPrefix: string
  hintRelativeText: string
  hintText: string
}>()
</script>

<template>
  <div v-if="loading" class="tab-loading">
    <div
      class="classify-hint classify-hint-skeleton"
      data-classify-hint="loading"
      data-last-classified-at=""
    >
      <el-skeleton animated>
        <template #template>
          <el-skeleton-item variant="text" class="hint-skel-line" />
        </template>
      </el-skeleton>
    </div>
    <el-skeleton v-for="idx in 3" :key="idx" animated />
  </div>

  <template v-else>
    <div
      class="classify-hint"
      :class="hintState"
      :data-classify-hint="hintState"
      :data-last-classified-at="lastClassifiedAt || ''"
      :title="hintTitle"
    >
      <el-icon><component :is="hintIcon" /></el-icon>
      <span class="classify-hint-copy">
        <template v-if="hintState === 'recent' || hintState === 'stale'">
          <span>{{ hintPrefix }}</span>
          <strong class="classify-hint-time">{{ hintRelativeText }}</strong>
        </template>
        <template v-else>{{ hintText }}</template>
      </span>
    </div>

    <el-empty
      v-if="items.length === 0"
      description="暂无相关推文，等待外部分类节拍"
      data-empty-state="no-tweets"
      class="empty-state"
    >
      <el-icon><ChatLineSquare /></el-icon>
    </el-empty>

    <article v-for="item in items" v-else :key="item.tweet_id" class="feed-row">
      <div class="feed-meta">
        <span>@{{ item.author_username || item.author }}</span>
        <span>{{ formatDateTime(item.created_at) }}</span>
        <span>{{ item.tweet_id }}</span>
      </div>
      <p class="tweet-text">{{ item.text }}</p>
      <div v-if="item.summary" class="summary-box">
        <span>AI 摘要</span>
        <p>{{ item.summary }}</p>
      </div>
    </article>
  </template>
</template>

<style scoped>
.feed-meta {
  font-family: var(--font-mono);
  font-size: var(--xs-font-size);
  color: var(--text-tertiary);
}

.empty-state {
  padding: 40px 16px;
}

.classify-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding: 10px 14px;
  margin: 0 0 12px;
  border: 1px solid var(--border-light);
  border-radius: var(--el-border-radius-base);
  background: var(--bg-inset);
  color: var(--text-secondary);
  font-size: var(--small-font-size);
  line-height: 1.6;
  overflow-wrap: anywhere;
}

.classify-hint .el-icon {
  flex-shrink: 0;
  color: var(--color-info);
  font-size: var(--body-font-size);
}

.classify-hint.stale .el-icon {
  color: var(--color-warning);
}

.classify-hint.never {
  background: var(--color-warning-light);
}

.classify-hint.never .el-icon {
  color: var(--color-warning);
}

.classify-hint-skeleton {
  display: block;
}

.hint-skel-line {
  width: 260px;
  max-width: 100%;
}

.classify-hint-copy {
  min-width: 0;
}

.classify-hint-time {
  color: var(--text-primary);
  font-family: var(--font-mono);
  font-size: var(--xs-font-size);
  font-weight: 600;
}

.classify-hint.stale .classify-hint-time {
  color: var(--color-warning);
}

.tab-loading {
  display: grid;
  gap: 12px;
}

.feed-row {
  padding: 14px 24px;
  margin-bottom: 12px;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--card-radius);
  box-shadow: var(--shadow-card);
  transition: box-shadow var(--transition-base), border-color var(--transition-base);
}

.feed-row:hover {
  border-color: var(--border-medium);
  box-shadow: var(--shadow-card-hover);
}

.feed-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 8px;
}

.tweet-text {
  margin: 0;
  color: var(--text-secondary);
  font-family: var(--font-reading);
  font-size: var(--reading-font-size);
  line-height: var(--reading-line-height);
  letter-spacing: var(--reading-letter-spacing);
  overflow-wrap: anywhere;
}

.summary-box {
  margin-top: 10px;
  padding: 8px 12px;
  border-left: 3px solid var(--color-primary-light);
  border-radius: var(--el-border-radius-small);
  background: var(--bg-inset);
}

.summary-box span {
  font-size: var(--label-font-size);
  color: var(--color-primary);
}

.summary-box p {
  margin: 4px 0 0;
  color: var(--text-secondary);
  line-height: 1.8;
  overflow-wrap: anywhere;
}
</style>
