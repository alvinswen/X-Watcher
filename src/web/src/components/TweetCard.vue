<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { CopyDocument } from "@element-plus/icons-vue"
import TweetLightbox from "@/components/TweetLightbox.vue"
import TweetMediaTiles from "@/components/TweetMediaTiles.vue"
import { formatFullDateTime } from "@/utils/format"
import { displaySummary, isCjkDominant } from "@/utils/tweetReading"
import type { TweetCardData } from "@/types/tweet"

const props = withDefaults(defineProps<{
  tweet: TweetCardData
  showAuthor?: boolean
  clickable?: boolean
  collapsibleOriginal?: boolean
  showShare?: boolean
  animationIndex?: number
  mediaHoverZoom?: boolean
  showRefMedia?: boolean
  readingMode?: boolean
}>(), {
  showAuthor: true,
  clickable: false,
  collapsibleOriginal: false,
  showShare: false,
  animationIndex: undefined,
  mediaHoverZoom: false,
  showRefMedia: false,
  readingMode: false,
})

const emit = defineEmits<{
  click: [tweetId: string]
  share: [tweet: TweetCardData]
}>()

const originalExpanded = ref(false)
const lightboxSrc = ref<string | null>(null)
const transExpanded = ref(false)
const origExpanded = ref(false)

const hasQuote = computed(() => props.tweet.referenced_tweet_id != null)
const zhNative = computed(() => isCjkDominant(props.tweet.text))
const hasTransLayer = computed(() => !!props.tweet.translation_text && !zhNative.value)
const origLayerHasText = computed(() => !!props.tweet.text && !!props.tweet.summary_text)
const hasOrigLayer = computed(() => origLayerHasText.value || hasQuote.value)
const isCardEmpty = computed(() => !props.tweet.summary_text && !props.tweet.text)
const l1Text = computed(() => props.tweet.summary_text
  ? displaySummary(props.tweet.summary_text, props.tweet.author_username, [])
  : (props.tweet.text || ""))
const relTagVisible = computed(() => props.readingMode
  && (props.tweet.reference_type != null || hasQuote.value))
const relTagText = computed(() => {
  const label = getReferenceLabel(props.tweet.reference_type)
  const author = props.tweet.referenced_tweet_author_username
  return author ? `${label} @${author}` : label
})

watch(() => props.tweet, () => {
  transExpanded.value = false
  origExpanded.value = false
}, { immediate: true })

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
      reading: readingMode,
      animated: animationIndex !== undefined,
      'media-hover-zoom': mediaHoverZoom,
    }"
    :style="animationIndex !== undefined ? { '--index': animationIndex } : undefined"
    data-testid="tweet-card"
    @click="handleCardClick"
  >
    <template v-if="readingMode">
      <div class="tweet-time-row">
        <span class="tweet-time">{{ formatFullDateTime(tweet.created_at) }}</span>
        <div v-if="showAuthor" class="tweet-author-inline">
          <span class="inline-author-name" :title="tweet.author_display_name || tweet.author_username">
            {{ tweet.author_display_name || tweet.author_username }}
          </span>
          <span class="inline-author-handle" :title="`@${tweet.author_username}`">@{{ tweet.author_username }}</span>
        </div>
        <span
          v-if="relTagVisible"
          class="rel-tag"
          data-testid="tweet-card-rel-tag"
        >{{ relTagText }}</span>
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

      <p
        v-if="isCardEmpty"
        class="empty-placeholder"
        data-testid="tweet-card-empty"
      >该推文无正文内容</p>
      <p v-else class="summary-line" data-testid="tweet-card-summary-line">{{ l1Text }}</p>

      <TweetMediaTiles
        v-if="tweet.media?.length"
        :items="tweet.media"
        :hover-zoom="mediaHoverZoom"
        @zoom="lightboxSrc = $event"
      />

      <div v-if="hasTransLayer || hasOrigLayer" class="layer-actions">
        <button
          v-if="hasTransLayer"
          type="button"
          class="layer-btn"
          :class="{ 'is-open': transExpanded }"
          data-testid="tweet-card-layer-btn"
          data-layer="trans"
          :aria-expanded="transExpanded"
          @click.stop="transExpanded = !transExpanded"
        >{{ transExpanded ? "▾ 收起全文" : "▸ 全文" }}</button>
        <button
          v-if="hasOrigLayer"
          type="button"
          class="layer-btn"
          :class="{ 'is-open': origExpanded }"
          data-testid="tweet-card-layer-btn"
          data-layer="orig"
          :aria-expanded="origExpanded"
          @click.stop="origExpanded = !origExpanded"
        >{{ origExpanded ? "▾ 收起原文" : "▸ 原文" }}</button>
      </div>

      <div
        v-if="transExpanded"
        class="layer layer--trans"
        data-testid="tweet-card-layer-trans"
      >{{ tweet.translation_text }}</div>

      <div
        v-if="origExpanded"
        class="layer layer--orig"
        data-testid="tweet-card-layer-orig"
      >
        <p v-if="origLayerHasText" class="layer-text">{{ tweet.text }}</p>
        <div
          v-if="hasQuote"
          class="quote-block"
          :class="{ 'quote-block--only': !origLayerHasText }"
          data-testid="tweet-card-ref-quote"
        >
          <span class="quote-attr">
            {{ tweet.referenced_tweet_author_username ? `↩ @${tweet.referenced_tweet_author_username} 原文` : "↩ 原文" }}
          </span>
          <p v-if="tweet.referenced_tweet_text" class="quote-text">{{ tweet.referenced_tweet_text }}</p>
          <TweetMediaTiles
            v-if="tweet.referenced_tweet_media?.length"
            :items="tweet.referenced_tweet_media"
            variant="ref"
            @zoom="lightboxSrc = $event"
          />
        </div>
      </div>
    </template>

    <template v-else>
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

      <TweetMediaTiles
        v-if="tweet.media?.length"
        :items="tweet.media"
        :hover-zoom="mediaHoverZoom"
        @zoom="lightboxSrc = $event"
      />

      <div v-if="tweet.referenced_tweet_id" class="referenced-tweet">
        <div class="ref-label">{{ getReferenceLabel(tweet.reference_type) }}</div>
        <div class="ref-content">
          <span class="ref-author">@{{ tweet.referenced_tweet_author_username }}</span>
          <span class="ref-text">{{ tweet.referenced_tweet_text }}</span>
        </div>
        <TweetMediaTiles
          v-if="showRefMedia && tweet.referenced_tweet_media?.length"
          :items="tweet.referenced_tweet_media"
          variant="ref"
          :hover-zoom="mediaHoverZoom"
          @zoom="lightboxSrc = $event"
        />
      </div>
    </template>

    <TweetLightbox
      v-if="lightboxSrc"
      :src="lightboxSrc"
      @close="lightboxSrc = null"
    />
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

.tweet-card.reading .tweet-time-row {
  justify-content: flex-start;
  gap: 12px;
}

.tweet-card.reading .tweet-author-inline {
  min-width: 0;
}

.tweet-card.reading .inline-author-name,
.tweet-card.reading .inline-author-handle {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tweet-card.reading .inline-author-name { max-width: 180px; }
.tweet-card.reading .inline-author-handle { max-width: 150px; }

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

.rel-tag {
  flex-shrink: 0;
  padding: 2px 6px;
  border: 1px solid var(--border-light);
  border-radius: var(--el-border-radius-small);
  background: var(--bg-inset);
  color: var(--text-secondary);
  font-size: var(--label-font-size);
  line-height: 1.5;
  letter-spacing: 0.05em;
  white-space: nowrap;
  cursor: default;
}

.summary-line,
.empty-placeholder {
  margin: 0;
  font-family: var(--font-reading);
  white-space: pre-wrap;
  word-break: break-word;
}

.summary-line {
  color: var(--text-primary);
  font-size: var(--summary-font-size);
  line-height: var(--reading-line-height);
  letter-spacing: var(--reading-letter-spacing);
}

.empty-placeholder {
  color: var(--text-secondary);
  font-size: var(--reading-font-size);
  line-height: var(--reading-line-height);
}

.layer-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.layer-btn {
  padding: 4px 8px;
  border: 1px solid var(--border-light);
  border-radius: var(--el-border-radius-small);
  background: none;
  color: var(--text-secondary);
  font-family: var(--font-ui);
  font-size: var(--xs-font-size);
  line-height: 1.6;
  cursor: pointer;
  transition: color var(--transition-base), border-color var(--transition-base), background-color var(--transition-base);
}

.layer-btn:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.layer-btn:active { background: var(--bg-inset); }

.layer-btn:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

.layer-btn.is-open {
  border-color: var(--color-primary);
  background: var(--bg-inset);
  color: var(--color-primary);
}

.layer {
  margin-top: 12px;
  padding: 12px 16px;
  border-radius: var(--el-border-radius-base);
  background: var(--bg-inset);
}

.layer-text,
.quote-text {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
}

.layer--trans {
  color: var(--text-primary);
  font-family: var(--font-reading);
  font-size: var(--reading-font-size);
  line-height: var(--reading-line-height);
  letter-spacing: var(--reading-letter-spacing);
  white-space: pre-wrap;
  word-break: break-word;
}

.layer--orig {
  color: var(--text-secondary);
  font-family: var(--font-reading);
  font-size: var(--small-font-size);
  line-height: 1.8;
}

.quote-block {
  margin-top: 12px;
  padding: 12px 16px;
  border-left: 2px solid var(--border-medium);
  border-radius: 0 var(--el-border-radius-base) var(--el-border-radius-base) 0;
  background: var(--bg-card);
  color: var(--text-secondary);
  font-family: var(--font-reading);
  font-size: var(--small-font-size);
  line-height: 1.8;
}

.quote-block--only { margin-top: 0; }

.quote-attr {
  display: block;
  margin-bottom: 6px;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
  font-size: var(--label-font-size);
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

.share-btn {
  margin-left: auto;
  padding: 2px 4px;
  color: var(--text-tertiary);
  transition: color var(--transition-base);
}

.share-btn:hover {
  color: var(--color-primary);
}

@media (prefers-reduced-motion: reduce) {
  .tweet-card,
  .layer-btn,
  .share-btn,
  .original-section.collapsible {
    transition: none !important;
  }
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
