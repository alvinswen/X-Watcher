<template>
  <ApiKeyGuideEmpty v-if="needsApiKey" />
  <div v-else class="search-view">
    <!-- 搜索栏 -->
    <el-form :inline="true" class="search-form" @submit.prevent="handleSearch">
      <el-form-item>
        <el-input
          v-model="searchQuery"
          placeholder="搜索关键词"
          clearable
          style="width: 300px"
          @keyup.enter="handleSearch"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
      </el-form-item>
      <el-form-item>
        <el-input
          v-model="authorFilter"
          placeholder="作者筛选"
          clearable
          style="width: 160px"
        />
      </el-form-item>
      <el-form-item>
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          value-format="YYYY-MM-DDTHH:mm:ss"
          style="width: 280px"
        />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="loading" @click="handleSearch">
          搜索
        </el-button>
      </el-form-item>
    </el-form>

    <!-- 结果统计 -->
    <div v-if="hasSearched && !loading" class="result-summary">
      共 {{ total }} 条结果
    </div>

    <!-- 加载状态 -->
    <el-skeleton v-if="loading" :rows="8" animated />

    <!-- 空状态 -->
    <el-empty
      v-else-if="hasSearched && items.length === 0"
      description="未找到匹配的推文"
    />

    <!-- 搜索结果列表 -->
    <div v-else-if="items.length > 0" class="tweet-list">
      <div
        v-for="tweet in items"
        :key="tweet.tweet_id"
        class="tweet-card"
        @click="goToDetail(tweet.tweet_id)"
      >
        <!-- 时间 + 作者 -->
        <div class="tweet-time-row">
          <span class="tweet-time">{{ formatFullDateTime(tweet.created_at) }}</span>
          <div class="tweet-author-inline">
            <span class="inline-author-name">
              {{ tweet.author_display_name || tweet.author_username }}
            </span>
            <span class="inline-author-handle">@{{ tweet.author_username }}</span>
          </div>
        </div>

        <!-- 摘要 -->
        <div v-if="tweet.summary_text" class="tweet-section summary-section">
          <div class="section-label">摘要</div>
          <div class="section-content">{{ tweet.summary_text }}</div>
        </div>

        <!-- 翻译 -->
        <div v-if="tweet.translation_text" class="tweet-section translation-section">
          <div class="section-label">翻译</div>
          <div class="section-content">{{ tweet.translation_text }}</div>
        </div>

        <!-- 原文 -->
        <div class="tweet-section original-section">
          <div class="section-label">原文</div>
          <div class="section-content original-text">{{ tweet.text }}</div>
        </div>

        <!-- 媒体 -->
        <div v-if="tweet.media && tweet.media.length > 0" class="tweet-media">
          <img
            v-for="(media, index) in tweet.media"
            :key="index"
            :src="media.url || media.preview_image_url || undefined"
            :alt="`媒体 ${index + 1}`"
            class="media-image"
          />
        </div>

        <!-- 引用推文 -->
        <div v-if="tweet.referenced_tweet_id" class="referenced-tweet">
          <div class="ref-label">{{ getReferenceLabel(tweet.reference_type) }}</div>
          <div class="ref-content">
            <span class="ref-author">@{{ tweet.referenced_tweet_author_username }}</span>
            <span class="ref-text">{{ tweet.referenced_tweet_text }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 分页 -->
    <div v-if="total > 0" class="pagination-bar">
      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        :total="total"
        layout="total, prev, pager, next"
        @current-change="handlePageChange"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue"
import { useRoute, useRouter } from "vue-router"
import { Search } from "@element-plus/icons-vue"
import { searchApi } from "@/api"
import ApiKeyGuideEmpty from "@/components/ApiKeyGuideEmpty.vue"
import { useApiKeyGuard } from "@/composables/useApiKeyGuard"
import { formatFullDateTime } from "@/utils/format"
import type { SearchTweetItem } from "@/types/search"

const route = useRoute()
const router = useRouter()

const searchQuery = ref("")
const authorFilter = ref("")
const dateRange = ref<[string, string] | null>(null)
const loading = ref(false)
const hasSearched = ref(false)

const items = ref<SearchTweetItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20

function getReferenceLabel(type: string | null): string {
  switch (type) {
    case "retweeted": return "转推"
    case "quoted": return "引用"
    case "replied_to": return "回复"
    default: return "引用"
  }
}

function goToDetail(tweetId: string) {
  router.push(`/tweets/${tweetId}`)
}

/** 从 URL query 恢复搜索状态 */
function restoreFromQuery() {
  const q = route.query.q as string
  if (q) {
    searchQuery.value = q
    authorFilter.value = (route.query.author as string) || ""
    page.value = parseInt(route.query.page as string) || 1
    if (route.query.since && route.query.until) {
      dateRange.value = [route.query.since as string, route.query.until as string]
    }
    doSearch()
  }
}

/** 同步搜索状态到 URL */
function syncToQuery() {
  const query: Record<string, string> = { q: searchQuery.value }
  if (authorFilter.value) query.author = authorFilter.value
  if (page.value > 1) query.page = String(page.value)
  if (dateRange.value) {
    query.since = dateRange.value[0]
    query.until = dateRange.value[1]
  }
  router.replace({ query })
}

async function doSearch() {
  if (!searchQuery.value.trim()) return

  loading.value = true
  hasSearched.value = true
  try {
    const result = await searchApi.searchTweets({
      q: searchQuery.value.trim(),
      author: authorFilter.value.trim().replace(/^@/, "") || undefined,
      since: dateRange.value?.[0] || undefined,
      until: dateRange.value?.[1] || undefined,
      page: page.value,
      page_size: pageSize,
    })
    items.value = result.items
    total.value = result.total
  } catch (error) {
    console.error("搜索失败:", error)
    items.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  page.value = 1
  syncToQuery()
  doSearch()
}

function handlePageChange(newPage: number) {
  page.value = newPage
  syncToQuery()
  doSearch()
}

const { needsApiKey } = useApiKeyGuard(restoreFromQuery)
</script>

<style scoped>
.search-view {
  max-width: 1200px;
  margin: 0 auto;
}

.search-form {
  margin-bottom: 16px;
}

.result-summary {
  font-size: var(--small-font-size);
  color: var(--text-secondary);
  margin-bottom: 16px;
  font-family: var(--font-mono);
}

.tweet-list {
  display: flex;
  flex-direction: column;
  gap: var(--card-gap);
  max-width: 720px;
}

.tweet-card {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--card-radius);
  padding: var(--card-padding);
  cursor: pointer;
  box-shadow: var(--shadow-card);
  transition: box-shadow var(--transition-base), transform var(--transition-base), border-color var(--transition-base);
}

.tweet-card:hover {
  box-shadow: var(--shadow-card-hover);
  transform: translateY(-1px);
  border-color: var(--border-medium);
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

.original-text {
  color: var(--text-tertiary);
  font-size: var(--small-font-size);
  line-height: 1.8;
}

.tweet-media {
  margin-top: 12px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 8px;
}

.media-image {
  width: 100%;
  border-radius: 6px;
  object-fit: cover;
  max-height: 200px;
}

.referenced-tweet {
  margin-top: 12px;
  padding: 12px 16px;
  background: var(--bg-inset);
  border-left: 2px solid var(--border-medium);
  border-radius: 0 6px 6px 0;
}

.ref-label {
  font-size: var(--label-font-size);
  color: var(--text-tertiary);
  margin-bottom: 4px;
}

.ref-content {
  font-size: var(--small-font-size);
  line-height: 1.7;
  color: var(--text-secondary);
  font-family: var(--font-reading);
}

.ref-author {
  font-weight: 500;
  color: var(--color-primary);
  font-family: var(--font-mono);
  margin-right: 6px;
}

.ref-text {
  white-space: pre-wrap;
  word-break: break-word;
}

.pagination-bar {
  display: flex;
  justify-content: center;
  padding: 20px 0;
}
</style>
