<script setup lang="ts">
import { Clock } from "@element-plus/icons-vue"
import type { SubjectDigest } from "@/types"
import { formatIntervalLabel } from "./subjectFormat"

defineProps<{
  loading: boolean
  digests: SubjectDigest[]
}>()
</script>

<template>
  <div v-if="loading" class="tab-loading">
    <el-skeleton v-for="idx in 2" :key="idx" animated />
  </div>

  <el-empty
    v-else-if="digests.length === 0"
    description="暂无滚动新闻，等待外部分类节拍"
    data-empty-state="no-tweets"
    class="empty-state"
  >
    <el-icon><Clock /></el-icon>
  </el-empty>

  <article
    v-for="(digest, index) in digests"
    v-else
    :key="`${digest.interval_start}-${digest.interval_end}-${digest.generated_at}-${index}`"
    class="digest-card"
    :data-interval-start="digest.interval_start"
    :data-interval-end="digest.interval_end"
  >
    <div class="digest-head">
      <span class="interval-pill">
        {{ formatIntervalLabel(digest.interval_start, digest.interval_end) }}
      </span>
      <span class="digest-count">{{ digest.tweet_count }} 条</span>
    </div>
    <p class="digest-text">{{ digest.digest_text }}</p>
    <el-collapse v-if="digest.highlights.length" class="highlight-collapse">
      <el-collapse-item
        v-for="(highlight, highlightIndex) in digest.highlights"
        :key="`${digest.interval_start}-${digest.interval_end}-${highlightIndex}`"
        :title="`引用 ${highlight.cited_tweet_ids.length} 条`"
        :name="`${digest.interval_start}-${digest.interval_end}-${highlightIndex}`"
      >
        <div
          class="highlight-item"
          :data-cited-tweet-ids="highlight.cited_tweet_ids.join(',')"
        >
          <p>{{ highlight.point }}</p>
          <code>{{ highlight.cited_tweet_ids.join(", ") }}</code>
        </div>
      </el-collapse-item>
    </el-collapse>
  </article>
</template>
