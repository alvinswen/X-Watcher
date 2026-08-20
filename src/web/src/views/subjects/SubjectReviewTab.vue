<script setup lang="ts">
import { computed } from "vue"
import { useRouter } from "vue-router"
import { ArrowDown, CircleClose, Document, Refresh } from "@element-plus/icons-vue"
import LoadErrorState from "@/components/LoadErrorState.vue"
import TweetCard from "@/components/TweetCard.vue"
import { formatRelativeTime } from "@/utils/format"
import { formatAbsoluteDateTime, splitParagraphs } from "@/views/subjects/subjectFormat"
import type {
  SubjectReview,
  SubjectReviewHistoryItem,
  SubjectReviewSection,
  TweetCardData,
} from "@/types"

const props = defineProps<{
  loading: boolean
  review: SubjectReview | null
  version: number
  latestVersion: number
  viewingVersion: number | null
  viewLoading: boolean
  historyItems: SubjectReviewHistoryItem[]
  historyLoading: boolean
  historyError: string
  sections: SubjectReviewSection[]
  hasTrend: boolean
  error: string
  pending: boolean
  refreshing: boolean
  requestButtonText: string
  updatedText: string
  openSections: string[]
  openCites: string[]
  retryReview: () => Promise<unknown>
}>()

const emit = defineEmits<{
  request: []
  "open-history": []
  "select-version": [version: number]
  "back-latest": []
  "retry-history": []
  "update:openSections": [value: string[]]
  "update:openCites": [value: string[]]
}>()

const openSectionsModel = computed({
  get: () => props.openSections,
  set: (value: string[]) => emit("update:openSections", value),
})
const openCitesModel = computed({
  get: () => props.openCites,
  set: (value: string[]) => emit("update:openCites", value),
})
const router = useRouter()
const citedTweetMap = computed(
  () => new Map<string, TweetCardData>(
    (props.review?.cited_tweets ?? []).map((tweet) => [tweet.tweet_id, tweet]),
  ),
)
const sectionParagraphs = computed(
  () => props.sections.map((section) => splitParagraphs(section.body)),
)

function reviewSectionName(index: number): string {
  return String(index)
}

function reviewCiteName(index: number): string {
  return `cite-${index}`
}

function goToDetail(id: string): void {
  router.push(`/tweets/${id}`)
}
</script>

<template>
  <div class="review-pane" :data-review-version="version">
    <div
      v-if="viewingVersion !== null"
      class="review-viewing-banner"
      :data-review-viewing="viewingVersion"
    >
      <span class="banner-text">
        正在查看历史版 <span class="banner-version">v{{ viewingVersion }}</span>
      </span>
      <button
        type="button"
        class="banner-back"
        data-review-back-latest
        @click="$emit('back-latest')"
      >
        回到最新
      </button>
    </div>

    <div v-if="(loading && !review) || viewLoading">
      <el-skeleton v-for="index in 2" :key="index" animated class="review-skeleton">
        <template #template>
          <el-skeleton-item variant="text" class="review-skel-time" />
          <el-skeleton-item variant="text" />
          <el-skeleton-item variant="text" />
          <el-skeleton-item variant="rect" class="review-skel-media" />
        </template>
      </el-skeleton>
    </div>

    <LoadErrorState v-else-if="error" :retry="retryReview" />

    <template v-else>
      <div class="review-infobar">
        <div class="review-info-left">
          <el-dropdown
            v-if="version >= 1"
            trigger="click"
            :teleported="false"
            @visible-change="(visible: boolean) => visible && $emit('open-history')"
            @command="(value: number) => value === latestVersion
              ? $emit('back-latest')
              : $emit('select-version', value)"
          >
            <button
              type="button"
              class="review-version-badge badge-trigger"
              :class="{ viewing: viewingVersion !== null }"
              :data-review-version-badge="version"
              data-review-history-trigger
            >
              v{{ version }}
              <el-icon class="badge-arrow"><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu class="review-history-panel" data-review-history-panel>
                <div
                  v-if="historyLoading"
                  class="history-row"
                  data-review-history-loading
                >
                  加载版本清单…
                </div>
                <div
                  v-else-if="historyError"
                  class="history-row history-error"
                  data-review-history-error
                >
                  <el-icon><CircleClose /></el-icon>
                  版本清单加载失败
                  <button
                    type="button"
                    class="history-retry"
                    data-review-history-retry
                    @click.stop="$emit('retry-history')"
                  >
                    重试
                  </button>
                </div>
                <template v-else>
                  <el-dropdown-item
                    v-for="item in historyItems"
                    :key="item.version"
                    :command="item.version"
                    :class="{ selected: item.version === version }"
                    :data-review-history-item="item.version"
                  >
                    <span class="history-version">v{{ item.version }}</span>
                    <span
                      v-if="item.version === latestVersion"
                      class="history-current"
                      data-review-history-current
                    >
                      当前
                    </span>
                    <el-tag
                      v-if="item.generated_by === 'fallback'"
                      type="warning"
                      size="small"
                      effect="plain"
                    >
                      降级生成
                    </el-tag>
                    <span
                      class="history-time"
                      :title="item.generated_at
                        ? formatAbsoluteDateTime(item.generated_at)
                        : undefined"
                    >
                      {{ formatRelativeTime(item.generated_at ?? null, "未知") }}
                    </span>
                  </el-dropdown-item>
                </template>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <span
            v-else
            class="review-version-badge empty"
            :data-review-version-badge="version"
          >
            v{{ version }}
          </span>
          <span class="review-updated">{{ updatedText }}</span>
          <el-tag
            v-if="review?.generated_by === 'fallback'"
            type="warning"
            size="small"
            effect="plain"
            data-review-fallback
          >
            降级生成
          </el-tag>
        </div>
        <div class="review-actions">
          <span v-if="pending" class="review-pending-badge" data-review-pending="true">
            已请求更新·待外部综述节拍处理
          </span>
          <el-button
            plain
            :icon="Refresh"
            :loading="refreshing"
            :disabled="refreshing || pending"
            data-review-request
            @click="$emit('request')"
          >
            {{ requestButtonText }}
          </el-button>
        </div>
      </div>

      <el-empty
        v-if="version === 0"
        description="暂无综述"
        data-empty-state="no-review"
        class="review-empty"
      >
        <template #image><el-icon data-empty-image><Document /></el-icon></template>
        <el-button
          plain
          :icon="Refresh"
          :loading="refreshing"
          :disabled="refreshing || pending"
          @click="$emit('request')"
        >
          {{ requestButtonText }}
        </el-button>
      </el-empty>

      <template v-else>
        <section v-if="hasTrend" class="review-trend" data-trend-block>
          <h3>
            本轮变化
            <span v-if="review?.prev_version">· 相对 v{{ review.prev_version }}</span>
          </h3>
          <div v-if="review?.trend.emerging.length" class="trend-group">
            <strong class="trend-label added">＋ 新增论点</strong>
            <ul>
              <li
                v-for="item in review.trend.emerging"
                :key="item"
                class="trend-item added"
              >
                <span>＋</span>{{ item }}
              </li>
            </ul>
          </div>
          <div v-if="review?.trend.fading.length" class="trend-group">
            <strong class="trend-label fading">↓ 淡出论点</strong>
            <ul>
              <li
                v-for="item in review.trend.fading"
                :key="item"
                class="trend-item fading"
              >
                <span>↓</span>{{ item }}
              </li>
            </ul>
          </div>
        </section>

        <el-collapse
          v-model="openSectionsModel"
          class="review-section-collapse"
          :data-sections-count="sections.length"
        >
          <el-collapse-item
            v-for="(section, index) in sections"
            :key="`${version}-${index}`"
            :name="reviewSectionName(index)"
            :data-review-section="index"
          >
            <template #title>
              <span class="review-section-title" :title="section.title">
                {{ section.title }}
              </span>
              <span class="review-section-count">
                引用 {{ section.cited_tweet_ids.length }} 条
              </span>
            </template>

            <div
              v-if="sectionParagraphs[index]?.length"
              class="review-section-body"
              :data-para-count="sectionParagraphs[index]?.length"
            >
              <p
                v-for="(paragraph, paraIndex) in sectionParagraphs[index] ?? []"
                :key="paraIndex"
                class="body-para"
                :data-para="paraIndex"
              >{{ paragraph }}</p>
            </div>

            <el-collapse
              v-if="section.cited_tweet_ids.length"
              v-model="openCitesModel"
              class="review-cite-collapse"
              data-cite-collapse
            >
              <el-collapse-item
                :name="reviewCiteName(index)"
                :title="`引用 ${section.cited_tweet_ids.length} 条`"
              >
                <div
                  class="review-cite-panel"
                  :data-cited-tweet-ids="section.cited_tweet_ids.join(',')"
                >
                  <template v-for="tweetId in section.cited_tweet_ids" :key="tweetId">
                    <TweetCard
                      v-if="citedTweetMap.has(tweetId)"
                      :tweet="citedTweetMap.get(tweetId)!"
                      clickable
                      collapsible-original
                      media-hover-zoom
                      show-ref-media
                      :data-cite-tweet-id="tweetId"
                      @click="goToDetail"
                    />
                    <div v-else class="cite-missing-row" :data-cite-missing-id="tweetId">
                      <span class="cite-missing-text">原推文暂不可查</span>
                      <code class="cite-missing-id">{{ tweetId }}</code>
                    </div>
                  </template>
                </div>
              </el-collapse-item>
            </el-collapse>
          </el-collapse-item>
        </el-collapse>
      </template>
    </template>
  </div>
</template>

<style scoped>
.review-pane {
  max-width: 720px; /* CHG-064 阅读列 · 与 BrowseView/SearchView .tweet-list 同口径 · 靠左（禁加 margin auto） */
  padding: 24px 28px;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--card-radius);
  box-shadow: var(--shadow-card);
}

.review-infobar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  padding-bottom: 16px;
  margin-bottom: 16px;
  border-bottom: 1px solid var(--border-light);
}

.review-info-left {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  min-width: 0;
}

.review-version-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 9px;
  border: 0;
  border-radius: var(--el-border-radius-base);
  color: var(--el-color-white);
  background: var(--color-primary);
  font-family: var(--font-mono);
  font-size: var(--small-font-size);
  font-weight: 600;
  line-height: 1.6;
  white-space: nowrap;
  cursor: pointer;
  transition: background var(--transition-base), color var(--transition-base), border-color var(--transition-base);
}

.badge-trigger:hover {
  background: var(--color-primary-dark);
}

.badge-arrow {
  display: inline-flex;
}

.review-version-badge.empty {
  background: var(--text-tertiary);
  cursor: default;
}

.review-version-badge.viewing {
  padding: 1px 8px;
  border: 1px solid var(--color-primary);
  background: var(--bg-inset);
  color: var(--color-primary);
}

.review-version-badge.viewing:hover {
  border-color: var(--color-primary-dark);
  background: var(--bg-inset);
  color: var(--color-primary-dark);
}

.badge-trigger:focus-visible,
.history-retry:focus-visible,
.banner-back:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

.review-history-panel {
  min-width: 240px;
  max-height: 320px;
  overflow-y: auto;
  padding: 4px 0;
  border: 1px solid var(--border-light);
  border-radius: var(--el-border-radius-base);
  background: var(--bg-card);
  box-shadow: var(--shadow-card-hover);
}

.review-history-panel :deep(.el-dropdown-menu__item) {
  gap: 8px;
  padding: 8px;
  color: var(--text-primary);
  font-size: var(--small-font-size);
  line-height: 1.6;
  transition: background var(--transition-base), color var(--transition-base);
}

.review-history-panel :deep(.el-dropdown-menu__item:hover) {
  background: var(--bg-inset);
}

.review-history-panel :deep(.el-dropdown-menu__item:active) {
  background: var(--border-light);
}

.review-history-panel :deep(.el-dropdown-menu__item.selected) {
  box-shadow: inset 3px 0 0 var(--color-primary);
  color: var(--color-primary);
}

.history-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  color: var(--text-tertiary);
  font-size: var(--small-font-size);
}

.history-error :deep(.el-icon) {
  flex-shrink: 0;
  color: var(--color-danger);
}

.history-retry,
.banner-back {
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--color-primary);
  font-family: var(--font-ui);
  font-size: inherit;
  line-height: inherit;
  cursor: pointer;
  text-decoration: none;
  transition: color var(--transition-base);
}

.history-retry {
  margin-left: auto;
}

.history-retry:hover,
.banner-back:hover {
  color: var(--color-primary-dark);
  text-decoration: underline;
}

.history-version,
.banner-version {
  font-family: var(--font-mono);
  font-weight: 600;
}

.history-current {
  flex-shrink: 0;
  padding: 1px 6px;
  border: 1px solid var(--color-primary);
  border-radius: var(--el-border-radius-small);
  color: var(--color-primary);
  font-size: var(--label-font-size);
  line-height: 1.5;
  white-space: nowrap;
}

.history-time {
  margin-left: auto;
  color: var(--text-tertiary);
  font-size: var(--small-font-size);
  white-space: nowrap;
  cursor: help;
}

.review-history-panel :deep(.el-dropdown-menu__item.selected) .history-time {
  color: var(--color-primary);
}

.review-viewing-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 4px 12px;
  padding: 12px 16px;
  margin-bottom: var(--section-gap);
  border-left: 3px solid var(--color-primary);
  border-radius: 0 var(--card-radius) var(--card-radius) 0;
  background: var(--color-primary-lighter);
  color: var(--text-primary);
  font-size: var(--small-font-size);
  line-height: 1.6;
}

.review-updated {
  color: var(--text-tertiary);
  font-size: var(--small-font-size);
  white-space: nowrap;
}

.review-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}

.review-pending-badge {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 2px 9px;
  border-radius: var(--el-border-radius-base);
  background: var(--bg-inset);
  color: var(--text-tertiary);
  font-size: var(--small-font-size);
  line-height: 1.6;
  white-space: nowrap;
}

.review-skeleton {
  display: grid;
  gap: 12px;
  margin-bottom: 20px;
  border: 1px solid var(--border-light);
  border-radius: var(--card-radius);
  background: var(--bg-card);
  padding: var(--card-padding);
}

.review-skel-time {
  width: 28%;
}

.review-skel-media {
  width: 100%;
  height: 180px;
}

.review-empty {
  padding: 56px 20px;
}

.review-empty :deep(.el-empty__image) {
  display: flex;
  justify-content: center;
  color: var(--text-tertiary);
  font-size: 64px;
  opacity: 0.7;
}

.review-trend {
  padding: 18px 20px;
  margin-bottom: 20px;
  border-left: 3px solid var(--color-primary);
  border-radius: 0 var(--card-radius) var(--card-radius) 0;
  background: var(--color-primary-lighter);
}

.review-trend h3 {
  margin: 0 0 14px;
  color: var(--text-primary);
  font-family: var(--font-reading);
  font-size: var(--summary-font-size);
  font-weight: 600;
}

.review-trend h3 span {
  color: var(--text-tertiary);
  font-family: var(--font-mono);
  font-size: var(--small-font-size);
  font-weight: 400;
}

.trend-group + .trend-group {
  padding-top: 14px;
  margin-top: 14px;
  border-top: 1px dashed var(--border-medium);
}

.trend-label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin-bottom: 8px;
  font-size: var(--small-font-size);
}

.trend-label.added {
  color: var(--color-success);
}

.trend-label.fading {
  color: var(--text-tertiary);
}

.review-trend ul {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 0;
  margin: 0;
  list-style: none;
}

.trend-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-family: var(--font-reading);
  font-size: var(--body-font-size);
  line-height: 1.7;
}

.trend-item span {
  flex-shrink: 0;
  font-family: var(--font-mono);
  font-weight: 700;
}

.trend-item.added span {
  color: var(--color-success);
}

.trend-item.fading {
  color: var(--text-tertiary);
}

.review-section-collapse {
  display: flex;
  flex-direction: column;
  gap: 20px;
  border: 0;
}

.review-section-collapse :deep(.el-collapse-item) {
  overflow: hidden;
  border: 1px solid var(--border-light);
  border-radius: var(--card-radius);
  background: var(--bg-card);
  box-shadow: var(--shadow-card);
  transition: border-color var(--transition-base), box-shadow var(--transition-base);
}

.review-section-collapse :deep(.el-collapse-item:hover) {
  border-color: var(--border-medium);
  box-shadow: var(--shadow-card-hover);
}

.review-section-collapse :deep(.el-collapse-item__header) {
  gap: 12px;
  height: auto;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-light);
  background: var(--bg-card);
  color: var(--text-primary);
  transition: background var(--transition-base);
}

.review-section-collapse :deep(.el-collapse-item__header:hover) {
  background: var(--bg-inset);
}

.review-section-collapse :deep(.el-collapse-item__wrap) {
  border-bottom: 0;
  background: var(--bg-card);
}

.review-section-collapse :deep(.el-collapse-item__content) {
  padding: 0 20px 20px;
  color: var(--text-primary);
}

.review-section-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  color: var(--text-primary);
  font-family: var(--font-reading);
  font-size: var(--summary-font-size);
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.review-section-count {
  flex-shrink: 0;
  padding: 2px 8px;
  border-radius: var(--el-border-radius-small);
  background: var(--bg-inset);
  color: var(--text-tertiary);
  font-family: var(--font-mono);
  font-size: var(--xs-font-size);
  white-space: nowrap;
}

.review-section-body {
  margin: 16px 0 0;
  color: var(--text-primary);
  font-family: var(--font-reading);
  font-size: var(--body-font-size);
  line-height: var(--reading-line-height);
  letter-spacing: var(--reading-letter-spacing);
  overflow-wrap: anywhere;
}

.review-section-body .body-para {
  margin: 0 0 calc(0.8 * var(--reading-line-height) * 1em);
}

.review-section-body .body-para:last-child {
  margin-bottom: 0;
}

.review-cite-collapse {
  padding-top: 12px;
  margin-top: 14px;
  border-top: 1px dashed var(--border-light);
  border-bottom: 0;
}

.review-cite-collapse :deep(.el-collapse-item) {
  border: 0;
  border-radius: 0;
  box-shadow: none;
  background: transparent;
}

.review-cite-collapse :deep(.el-collapse-item__header) {
  padding: 0;
  border-bottom: 0;
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--small-font-size);
}

.review-cite-collapse :deep(.el-collapse-item__content) {
  padding: 12px 0 0;
}

.review-cite-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
  border-radius: var(--el-border-radius-base);
  background: var(--bg-inset);
}

.cite-missing-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: var(--el-border-radius-base);
  background: var(--bg-inset);
  cursor: default;
}

.cite-missing-text {
  color: var(--text-secondary);
  font-size: var(--small-font-size);
}

.cite-missing-id {
  padding: 1px 7px;
  border-radius: var(--el-border-radius-small);
  background: var(--bg-card);
  color: var(--text-tertiary);
  font-family: var(--font-mono);
  font-size: var(--label-font-size);
}
</style>
