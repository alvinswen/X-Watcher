<script setup lang="ts">
import { computed } from "vue"
import { Clock } from "@element-plus/icons-vue"
import type { SubjectDigest } from "@/types"
import { formatIntervalLabel, splitParagraphs } from "./subjectFormat"

const props = defineProps<{
  loading: boolean
  digests: SubjectDigest[]
}>()

const digestParagraphs = computed(
  () => props.digests.map((digest) => splitParagraphs(digest.digest_text)),
)
</script>

<template>
  <div class="digest-pane">
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
      <div
        v-if="digestParagraphs[index]?.length"
        class="digest-text"
        :data-para-count="digestParagraphs[index]?.length"
      >
        <p
          v-for="(paragraph, paraIndex) in digestParagraphs[index] ?? []"
          :key="paraIndex"
          class="body-para"
          :data-para="paraIndex"
        >{{ paragraph }}</p>
      </div>
      <el-collapse
        v-if="digest.highlights.length"
        class="highlight-collapse"
        data-highlight-collapse
      >
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
  </div>
</template>

<style scoped>
.digest-count {
  font-family: var(--font-mono);
  font-size: var(--xs-font-size);
  color: var(--text-tertiary);
}

.empty-state {
  padding: 40px 16px;
}

.tab-loading {
  display: grid;
  gap: 12px;
}

.digest-card {
  padding: 14px 24px;
  margin-bottom: 12px;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--card-radius);
  box-shadow: var(--shadow-card);
  transition: box-shadow var(--transition-base), border-color var(--transition-base);
}

.digest-card:hover {
  border-color: var(--border-medium);
  box-shadow: var(--shadow-card-hover);
}

.digest-text {
  margin: 0;
  color: var(--text-secondary);
  font-family: var(--font-reading);
  font-size: var(--reading-font-size);
  line-height: var(--reading-line-height);
  letter-spacing: var(--reading-letter-spacing);
  overflow-wrap: anywhere;
}

.digest-pane {
  max-width: 720px; /* CHG-064 阅读列 · 同 .review-pane 口径 · 靠左（禁加 margin auto） */
}

.digest-text .body-para {
  margin: 0 0 calc(0.8 * var(--reading-line-height) * 1em);
}

.digest-text .body-para:last-child {
  margin-bottom: 0;
}

.digest-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.interval-pill {
  padding: 2px 8px;
  border-radius: var(--el-border-radius-small);
  background: var(--bg-inset);
  color: var(--text-tertiary);
  font-family: var(--font-mono);
  font-size: var(--xs-font-size);
}

.highlight-collapse {
  padding-top: 12px;
  margin-top: 14px;
  border-top: 1px dashed var(--border-light);
  border-bottom: 0;
}

.highlight-collapse :deep(.el-collapse-item) {
  border: 0;
  border-radius: 0;
  box-shadow: none;
  background: transparent;
}

.highlight-collapse :deep(.el-collapse-item__header) {
  padding: 0;
  border-bottom: 0;
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--small-font-size);
}

.highlight-collapse :deep(.el-collapse-item__content) {
  padding: 12px 0 0;
}

.highlight-item {
  padding: 8px 12px;
  border-left: 3px solid var(--color-primary-light);
  border-radius: var(--el-border-radius-small);
  background: var(--bg-inset);
}

.highlight-item p {
  margin: 0 0 6px;
  color: var(--text-secondary);
  line-height: 1.8;
}

.highlight-item code {
  color: var(--text-tertiary);
  font-family: var(--font-mono);
  font-size: var(--xs-font-size);
}
</style>
