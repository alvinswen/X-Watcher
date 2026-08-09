<template>
  <ApiKeyGuideEmpty v-if="needsApiKey" />
  <div v-else class="search-view" data-testid="search-view">
    <!-- 搜索栏 -->
    <el-form :inline="true" class="search-form" @submit.prevent="handleSearch">
      <el-form-item>
        <el-input
          v-model="searchQuery"
          placeholder="搜索关键词"
          clearable
          style="width: 300px"
          data-testid="search-input"
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
          data-testid="search-author-filter"
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
          data-testid="search-date-range"
        />
      </el-form-item>
      <el-form-item>
        <el-button
          type="primary"
          :loading="loading"
          data-testid="search-submit"
          @click="handleSearch"
        >
          搜索
        </el-button>
      </el-form-item>
    </el-form>

    <!-- 结果统计 -->
    <div v-if="hasSearched && !loading && !loadError" class="result-summary">
      共 {{ total }} 条结果
    </div>

    <!-- 加载状态 -->
    <el-skeleton v-if="loading" :rows="8" animated />

    <LoadErrorState v-else-if="loadError" :retry="retrySearch" />

    <!-- 空状态 -->
    <el-empty
      v-else-if="hasSearched && items.length === 0"
      description="未找到匹配的推文"
    />

    <!-- 搜索结果列表 -->
    <div
      v-else-if="items.length > 0"
      class="tweet-list"
      data-testid="search-results"
    >
      <TweetCard
        v-for="tweet in items"
        :key="tweet.tweet_id"
        :tweet="tweet"
        reading-mode
        :highlight-terms="activeTerms"
        clickable
        @click="goToDetail"
      />
    </div>

    <!-- 分页 -->
    <div
      v-if="!loadError && total > 0"
      class="pagination-bar"
      data-testid="search-pagination"
    >
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
import LoadErrorState from "@/components/LoadErrorState.vue"
import TweetCard from "@/components/TweetCard.vue"
import { useApiKeyGuard } from "@/composables/useApiKeyGuard"
import { splitSearchTerms } from "@/utils/tweetReading"
import type { SearchTweetItem } from "@/types/search"

const route = useRoute()
const router = useRouter()

const searchQuery = ref("")
const authorFilter = ref("")
const dateRange = ref<[string, string] | null>(null)
const loading = ref(false)
const hasSearched = ref(false)
const loadError = ref(false)
const activeTerms = ref<string[]>([])

const items = ref<SearchTweetItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20

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

async function doSearch(preserveError = false) {
  if (!searchQuery.value.trim()) return

  activeTerms.value = splitSearchTerms(searchQuery.value)
  loading.value = !preserveError
  hasSearched.value = true
  if (!preserveError) {
    loadError.value = false
  }
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
    loadError.value = false
  } catch (error) {
    console.error("搜索失败:", error)
    items.value = []
    total.value = 0
    loadError.value = true
  } finally {
    loading.value = false
  }
}

function retrySearch() {
  return doSearch(true)
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

.pagination-bar {
  display: flex;
  justify-content: center;
  padding: 20px 0;
}
</style>
