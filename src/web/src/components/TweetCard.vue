<script setup lang="ts">
import { ref } from "vue"
import { CopyDocument } from "@element-plus/icons-vue"
import { formatFullDateTime } from "@/utils/format"
import type { TweetCardData } from "@/types/tweet"

const props = withDefaults(defineProps<{
  tweet: TweetCardData
  showAuthor?: boolean
  clickable?: boolean
  collapsibleOriginal?: boolean
  showShare?: boolean
  animationIndex?: number
  mediaHoverZoom?: boolean
}>(), {
  showAuthor: true,
  clickable: false,
  collapsibleOriginal: false,
  showShare: false,
  animationIndex: undefined,
  mediaHoverZoom: false,
})

const emit = defineEmits<{
  click: [tweetId: string]
  share: [tweet: TweetCardData]
}>()

const originalExpanded = ref(false)

function getReferenceLabel(type: string | null): string {
  switch (type) {
    case "retweeted": return "转推"
    case "quoted": return "引用"
    case "replied_to": return "回复"
    default: return "引用"
  }
}

function handleCardClick() {
  if (props.clickable) {
    emit("click", props.tweet.tweet_id)
  }
}

function toggleOriginal() {
  if (props.collapsibleOriginal) {
    originalExpanded.value = !originalExpanded.value
  }
}
</script>

<template>
  <article
    class="tweet-card"
    :class="{
      clickable,
      animated: animationIndex !== undefined,
      'media-hover-zoom': mediaHoverZoom,
    }"
    :style="animationIndex !== undefined ? { '--index': animationIndex } : undefined"
    data-testid="tweet-card"
    @click="handleCardClick"
  >
    <div class="tweet-time-row">
      <span class="tweet-time">{{ formatFullDateTime(tweet.created_at) }}</span>
      <div v-if="showAuthor" class="tweet-author-inline">
        <span class="inline-author-name">
          {{ tweet.author_display_name || tweet.author_username }}
        </span>
        <span class="inline-author-handle">@{{ tweet.author_username }}</span>
      </div>
      <el-button
        v-if="showShare"
        text
        size="small"
        class="share-btn"
        title="复制为 Markdown"
        data-testid="tweet-card-share"
        @click.stop="emit('share', tweet)"
      >
        <el-icon :size="14"><CopyDocument /></el-icon>
      </el-button>
    </div>

    <div v-if="tweet.summary_text" class="tweet-section summary-section">
      <div class="section-label" data-testid="tweet-card-summary-label">摘要</div>
      <div class="section-content">{{ tweet.summary_text }}</div>
    </div>

    <div v-if="tweet.translation_text" class="tweet-section translation-section">
      <div class="section-label">翻译</div>
      <div class="section-content" data-testid="tweet-card-translation">
        {{ tweet.translation_text }}
      </div>
    </div>

    <div
      class="tweet-section original-section"
      :class="{
        collapsible: collapsibleOriginal,
        expanded: originalExpanded,
      }"
      @click.stop="toggleOriginal"
    >
      <div class="section-label">原文</div>
      <div class="section-content original-text">{{ tweet.text }}</div>
      <div
        v-if="collapsibleOriginal && !originalExpanded"
        class="original-fade-mask"
      />
    </div>

    <div v-if="tweet.media?.length" class="tweet-media">
      <img
        v-for="(media, index) in tweet.media"
        :key="index"
        :src="media.url || media.preview_image_url || undefined"
        :alt="`媒体 ${index + 1}`"
        class="media-image"
      />
    </div>

    <div v-if="tweet.referenced_tweet_id" class="referenced-tweet">
      <div class="ref-label">{{ getReferenceLabel(tweet.reference_type) }}</div>
      <div class="ref-content">
        <span class="ref-author">@{{ tweet.referenced_tweet_author_username }}</span>
        <span class="ref-text">{{ tweet.referenced_tweet_text }}</span>
      </div>
      <div
        v-if="collapsibleOriginal && tweet.referenced_tweet_media?.length"
        class="tweet-media ref-media"
      >
        <img
          v-for="(media, index) in tweet.referenced_tweet_media"
          :key="index"
          :src="media.url || media.preview_image_url || undefined"
          :alt="`引用媒体 ${index + 1}`"
          class="media-image"
        />
      </div>
    </div>
  </article>
</template>

<style scoped>
.tweet-card {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--card-radius);
  padding: var(--card-padding);
  box-shadow: var(--shadow-card);
  transition: box-shadow var(--transition-base), transform var(--transition-base), border-color var(--transition-base);
}

.tweet-card:hover {
  box-shadow: var(--shadow-card-hover);
  transform: translateY(-1px);
  border-color: var(--border-medium);
}

.tweet-card.clickable {
  cursor: pointer;
}

.tweet-card.animated {
  animation: card-enter 0.4s ease both;
  animation-delay: calc(var(--index, 0) * 60ms);
}

.tweet-time-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border-light);
}

.tweet-time {
  font-size: var(--xs-font-size);
  color: var(--text-tertiary);
  font-family: var(--font-mono);
}

.tweet-author-inline {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.inline-author-name {
  font-size: var(--small-font-size);
  font-weight: 600;
  color: var(--text-primary);
}

.inline-author-handle {
  font-size: var(--xs-font-size);
  color: var(--text-tertiary);
  font-family: var(--font-mono);
}

.tweet-section {
  margin-bottom: var(--section-gap);
}

.tweet-section:last-child {
  margin-bottom: 0;
}

.section-label {
  font-size: var(--label-font-size);
  color: var(--text-tertiary);
  margin-bottom: 6px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.section-content {
  font-size: var(--reading-font-size);
  line-height: var(--reading-line-height);
  letter-spacing: var(--reading-letter-spacing);
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--font-reading);
}

.summary-section .section-content {
  font-size: var(--summary-font-size);
}

.translation-section .section-content {
  background: var(--bg-inset);
  padding: 12px 16px;
  border-radius: 6px;
  border-left: 3px solid var(--color-primary);
}

.original-section.collapsible {
  position: relative;
  cursor: pointer;
  max-height: 5.6em;
  overflow: hidden;
  transition: max-height 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}

.original-section.collapsible.expanded {
  max-height: none;
  cursor: default;
}

.original-text {
  color: var(--text-tertiary);
  font-size: var(--small-font-size);
  line-height: 1.8;
  font-family: var(--font-reading);
}

.original-fade-mask {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  height: 2.4em;
  background: linear-gradient(transparent, var(--bg-card));
  pointer-events: none;
}

.tweet-media {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 8px;
  margin-top: 12px;
}

.media-image {
  width: 100%;
  max-height: 200px;
  border-radius: 6px;
  object-fit: cover;
}

.media-hover-zoom .media-image {
  transition: transform var(--transition-base);
}

.media-hover-zoom .media-image:hover {
  transform: scale(1.02);
}

.referenced-tweet {
  margin-top: 12px;
  padding: 12px 16px;
  background: var(--bg-inset);
  border-left: 2px solid var(--border-medium);
  border-radius: 0 6px 6px 0;
}

.ref-label {
  margin-bottom: 4px;
  color: var(--text-tertiary);
  font-size: var(--label-font-size);
}

.ref-content {
  color: var(--text-secondary);
  font-size: var(--small-font-size);
  line-height: 1.7;
  font-family: var(--font-reading);
}

.ref-author {
  margin-right: 6px;
  color: var(--color-primary);
  font-weight: 500;
  font-family: var(--font-mono);
}

.ref-text {
  white-space: pre-wrap;
  word-break: break-word;
}

.ref-media {
  margin-top: 6px;
}

.share-btn {
  margin-left: auto;
  padding: 2px 4px;
  color: var(--text-tertiary);
  transition: color var(--transition-base);
}

.share-btn:hover {
  color: var(--color-primary);
}

@keyframes card-enter {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
</style>
