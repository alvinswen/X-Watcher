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
