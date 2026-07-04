<template>
  <div class="tweets-view">
    <div class="page-header">
      <h1>推文列表</h1>
      <el-button :icon="Refresh" @click="handleRefresh" :loading="loading">
        刷新
      </el-button>
    </div>

    <!-- 筛选器 -->
    <div class="filters">
      <el-input
        v-model="filterAuthor"
        placeholder="按作者筛选"
        clearable
        style="width: 200px"
        @clear="handleFilterChange"
        @keyup.enter="handleFilterChange"
      >
        <template #append>
          <el-button :icon="Search" @click="handleFilterChange" />
        </template>
      </el-input>
    </div>

    <!-- 加载状态 -->
    <el-skeleton v-if="loading && tweets.length === 0" :rows="5" animated />

    <!-- 空状态 -->
    <el-empty v-else-if="!loading && tweets.length === 0" description="暂无推文数据" />

    <!-- 推文列表 -->
    <div v-else class="tweet-list">
      <div
        v-for="tweet in tweets"
        :key="tweet.tweet_id"
        class="tweet-card-wrapper"
      >
        <div
          class="tweet-card"
          @click="handleTweetClick(tweet.tweet_id)"
        >
          <div class="tweet-header">
            <span class="tweet-author">{{ tweet.author_display_name || tweet.author_username }}</span>
            <span class="tweet-username">@{{ tweet.author_username }}</span>
            <span class="tweet-time">
              {{ formatRelativeTime(tweet.created_at) }}
              <span class="tweet-db-time">入库: {{ formatRelativeTime(tweet.db_created_at) }}</span>
            </span>
          </div>
          <div class="tweet-content">{{ tweet.text }}</div>
          <div class="tweet-footer">
            <el-tag v-if="tweet.has_summary" type="success" size="small">已摘要</el-tag>
            <el-tag v-else type="info" size="small">暂无摘要 · 摘要由 Agent 生成</el-tag>
            <el-tag v-if="tweet.media_count > 0" size="small">
              {{ tweet.media_count }} 媒体
            </el-tag>
          </div>
        </div>
      </div>
    </div>

    <!-- 分页 -->
    <div v-if="totalPages > 1" class="pagination">
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[10, 20, 50, 100]"
        :total="total"
        layout="total, sizes, prev, pager, next, jumper"
        @current-change="handlePageChange"
        @size-change="handleSizeChange"
      />
    </div>

  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from "vue"
import { useRouter } from "vue-router"
import { Refresh, Search } from "@element-plus/icons-vue"
import { tweetsApi } from "@/api"
import { formatRelativeTime } from "@/utils/format"
import type { TweetListItem } from "@/types"

/** 路由实例 */
const router = useRouter()

/** 推文列表 */
const tweets = ref<TweetListItem[]>([])

/** 总数量 */
const total = ref(0)

/** 当前页码 */
const currentPage = ref(1)

/** 每页数量 */
const pageSize = ref(20)

/** 总页数 */
const totalPages = ref(0)

/** 加载状态 */
const loading = ref(false)

/** 作者筛选 */
const filterAuthor = ref("")

/** 加载推文列表 */
async function loadTweets() {
  loading.value = true
  try {
    const response = await tweetsApi.getList({
      page: currentPage.value,
      page_size: pageSize.value,
      author: filterAuthor.value || undefined,
    })
    tweets.value = response.items
    total.value = response.total
    totalPages.value = response.total_pages
  } catch (error) {
    // 错误已被 API 拦截器处理
    console.error("加载推文列表失败:", error)
  } finally {
    loading.value = false
  }
}

/** 刷新列表 */
function handleRefresh() {
  currentPage.value = 1
  loadTweets()
}

/** 筛选变化 */
function handleFilterChange() {
  currentPage.value = 1
  loadTweets()
}

/** 页码变化 */
function handlePageChange(page: number) {
  currentPage.value = page
  loadTweets()
}

/** 每页数量变化 */
function handleSizeChange(size: number) {
  pageSize.value = size
  currentPage.value = 1
  loadTweets()
}

/** 点击推文 */
function handleTweetClick(tweetId: string) {
  router.push(`/tweets/${tweetId}`)
}

/** 组件挂载时加载数据 */
onMounted(() => {
  loadTweets()
})
</script>

<style scoped>
.tweets-view {
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1.5rem;
}

.page-header h1 {
  margin: 0;
  font-size: 1.5rem;
  color: #333;
}

.filters {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.tweet-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.tweet-card-wrapper {
  display: block;
}

.tweet-card {
  flex: 1;
  padding: 1rem;
  background-color: #fff;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  cursor: pointer;
  transition: box-shadow 0.2s, transform 0.2s;
}

.tweet-card:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  transform: translateY(-2px);
}

.tweet-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}

.tweet-author {
  font-weight: 600;
  color: #333;
}

.tweet-username {
  color: #666;
  font-size: 0.875rem;
}

.tweet-time {
  margin-left: auto;
  color: #999;
  font-size: 0.75rem;
  text-align: right;
  white-space: nowrap;
}

.tweet-db-time {
  margin-left: 0.75rem;
  color: #bbb;
}

.tweet-content {
  color: #333;
  line-height: 1.6;
  margin-bottom: 0.75rem;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.tweet-footer {
  display: flex;
  gap: 0.5rem;
}

.pagination {
  margin-top: 1.5rem;
  display: flex;
  justify-content: center;
}
</style>
