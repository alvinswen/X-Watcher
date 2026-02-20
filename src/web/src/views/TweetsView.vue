<template>
  <div class="tweets-view">
    <div class="page-header">
      <h1>推文列表</h1>
      <el-button :icon="Refresh" @click="handleRefresh" :loading="loading">
        刷新
      </el-button>
    </div>

    <!-- 筛选器与批量操作栏 -->
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

      <div class="batch-actions">
        <el-checkbox
          v-model="selectAll"
          :indeterminate="isIndeterminate"
          @change="handleSelectAll"
        >
          全选
        </el-checkbox>
        <span v-if="selectedTweetIds.size > 0" class="selected-count">
          已选 {{ selectedTweetIds.size }} 条
        </span>
        <el-tooltip content="请先选择推文" :disabled="selectedTweetIds.size > 0" placement="top">
          <el-button
            type="primary"
            size="small"
            :disabled="selectedTweetIds.size === 0"
            :loading="batchSummarizing"
            @click="handleBatchSummarize"
          >
            批量摘要
          </el-button>
        </el-tooltip>
        <el-dropdown @command="handleSummaryToolCommand">
          <el-button type="info" size="small">
            摘要工具 <el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="backfill">摘要补缺</el-dropdown-item>
              <el-dropdown-item command="reset">摘要重置</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
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
        <el-checkbox
          class="tweet-checkbox"
          :model-value="selectedTweetIds.has(tweet.tweet_id)"
          @change="(val: boolean) => handleToggleSelect(tweet.tweet_id, val)"
        />
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
            <el-tag v-else type="info" size="small">未摘要</el-tag>
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

    <!-- 摘要补缺对话框 -->
    <el-dialog v-model="backfillDialogVisible" title="摘要补缺" width="500">
      <p style="margin-bottom: 1rem; color: #666;">为缺少摘要的推文批量生成摘要和翻译。可选指定时间范围。</p>
      <el-date-picker
        v-model="backfillDateRange"
        type="datetimerange"
        range-separator="至"
        start-placeholder="起始时间（可选）"
        end-placeholder="截止时间（可选）"
        style="width: 100%; margin-bottom: 1rem;"
      />
      <div v-if="backfillPreviewCount !== null" style="margin-bottom: 1rem;">
        <el-tag type="info" size="large">待补缺推文: {{ backfillPreviewCount }} 条</el-tag>
      </div>
      <template #footer>
        <el-button @click="handleBackfillPreview" :loading="backfillLoading">查询数量</el-button>
        <el-button
          type="primary"
          @click="handleBackfillExecute"
          :loading="backfillTaskRunning"
          :disabled="backfillPreviewCount === null || backfillPreviewCount === 0"
        >
          执行补缺
        </el-button>
      </template>
    </el-dialog>

    <!-- 摘要重置对话框 -->
    <el-dialog v-model="resetDialogVisible" title="摘要重置" width="500">
      <el-alert type="warning" title="此操作将覆盖现有摘要" show-icon :closable="false" style="margin-bottom: 1rem;" />
      <p style="margin-bottom: 1rem; color: #666;">对指定时间范围内所有推文重新生成摘要。必须指定时间范围。</p>
      <el-date-picker
        v-model="resetDateRange"
        type="datetimerange"
        range-separator="至"
        start-placeholder="起始时间"
        end-placeholder="截止时间"
        style="width: 100%; margin-bottom: 1rem;"
      />
      <div v-if="resetPreviewCount !== null" style="margin-bottom: 1rem;">
        <el-tag type="warning" size="large">范围内推文: {{ resetPreviewCount }} 条</el-tag>
      </div>
      <template #footer>
        <el-button @click="handleResetPreview" :loading="resetLoading" :disabled="!resetDateRange">查询数量</el-button>
        <el-button
          type="danger"
          @click="handleResetExecute"
          :loading="resetTaskRunning"
          :disabled="resetPreviewCount === null || resetPreviewCount === 0"
        >
          执行重置
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from "vue"
import { useRouter } from "vue-router"
import { ArrowDown, Refresh, Search } from "@element-plus/icons-vue"
import { ElMessage } from "element-plus"
import { tweetsApi, summariesApi } from "@/api"
import { taskPollingService } from "@/services/polling"
import { formatRelativeTime } from "@/utils/format"
import type { TweetListItem, TaskStatusResponse } from "@/types"

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

/** 选中的推文 ID 集合 */
const selectedTweetIds = ref<Set<string>>(new Set())

/** 全选状态 */
const selectAll = ref(false)

/** 半选状态 */
const isIndeterminate = computed(() => {
  const size = selectedTweetIds.value.size
  return size > 0 && size < tweets.value.length
})

/** 批量摘要状态 */
const batchSummarizing = ref(false)

/** 补缺对话框 */
const backfillDialogVisible = ref(false)
const backfillDateRange = ref<[Date, Date] | null>(null)
const backfillPreviewCount = ref<number | null>(null)
const backfillLoading = ref(false)
const backfillTaskRunning = ref(false)

/** 重置对话框 */
const resetDialogVisible = ref(false)
const resetDateRange = ref<[Date, Date] | null>(null)
const resetPreviewCount = ref<number | null>(null)
const resetLoading = ref(false)
const resetTaskRunning = ref(false)

/** 轮询句柄 */
let pollingHandle: { cancel: () => void } | null = null

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

/** 切换单个推文选中状态 */
function handleToggleSelect(tweetId: string, checked: boolean) {
  const newSet = new Set(selectedTweetIds.value)
  if (checked) {
    newSet.add(tweetId)
  } else {
    newSet.delete(tweetId)
  }
  selectedTweetIds.value = newSet
  selectAll.value = newSet.size === tweets.value.length
}

/** 全选/取消全选 */
function handleSelectAll(checked: boolean | string | number) {
  const newSet = new Set<string>()
  if (checked) {
    tweets.value.forEach((t) => newSet.add(t.tweet_id))
  }
  selectedTweetIds.value = newSet
  selectAll.value = !!checked
}

/** 批量摘要 */
async function handleBatchSummarize() {
  if (selectedTweetIds.value.size === 0) return

  batchSummarizing.value = true
  try {
    const response = await summariesApi.batchSummarize(
      Array.from(selectedTweetIds.value),
    )
    ElMessage.success("批量摘要任务已提交")

    // 启动轮询
    pollingHandle = taskPollingService.startPolling(
      response.task_id,
      async () => {
        const status = await summariesApi.getTaskStatus(response.task_id)
        return status as TaskStatusResponse
      },
      () => {
        // 状态更新（无需额外操作）
      },
      () => {
        // 任务完成
        ElMessage.success("批量摘要完成")
        selectedTweetIds.value = new Set()
        selectAll.value = false
        batchSummarizing.value = false
        loadTweets()
      },
      (error) => {
        console.error("批量摘要轮询失败:", error)
        batchSummarizing.value = false
      },
    )
  } catch (error) {
    console.error("批量摘要失败:", error)
    ElMessage.error("批量摘要提交失败")
    batchSummarizing.value = false
  }
}

/** 摘要工具下拉命令 */
function handleSummaryToolCommand(command: string) {
  if (command === "backfill") {
    backfillDateRange.value = null
    backfillPreviewCount.value = null
    backfillDialogVisible.value = true
  } else if (command === "reset") {
    resetDateRange.value = null
    resetPreviewCount.value = null
    resetDialogVisible.value = true
  }
}

/** 补缺预览 */
async function handleBackfillPreview() {
  backfillLoading.value = true
  try {
    const params: { since?: string; until?: string } = {}
    if (backfillDateRange.value) {
      params.since = backfillDateRange.value[0].toISOString()
      params.until = backfillDateRange.value[1].toISOString()
    }
    const result = await summariesApi.previewBackfill(params)
    backfillPreviewCount.value = result.tweet_count
  } catch (error) {
    console.error("补缺预览失败:", error)
    ElMessage.error("查询失败")
  } finally {
    backfillLoading.value = false
  }
}

/** 执行补缺 */
async function handleBackfillExecute() {
  backfillTaskRunning.value = true
  try {
    const params: { since?: string; until?: string } = {}
    if (backfillDateRange.value) {
      params.since = backfillDateRange.value[0].toISOString()
      params.until = backfillDateRange.value[1].toISOString()
    }
    const response = await summariesApi.startBackfill(params)
    ElMessage.success(`补缺任务已提交，共 ${response.tweet_count} 条推文`)
    backfillDialogVisible.value = false

    pollingHandle = taskPollingService.startPolling(
      response.task_id,
      async () => await summariesApi.getTaskStatus(response.task_id) as TaskStatusResponse,
      () => {},
      () => {
        ElMessage.success("摘要补缺完成")
        backfillTaskRunning.value = false
        loadTweets()
      },
      (error) => {
        console.error("补缺轮询失败:", error)
        backfillTaskRunning.value = false
      },
    )
  } catch (error) {
    console.error("补缺执行失败:", error)
    ElMessage.error("补缺提交失败")
    backfillTaskRunning.value = false
  }
}

/** 重置预览 */
async function handleResetPreview() {
  if (!resetDateRange.value) {
    ElMessage.warning("请选择时间范围")
    return
  }
  resetLoading.value = true
  try {
    const result = await summariesApi.previewReset({
      since: resetDateRange.value[0].toISOString(),
      until: resetDateRange.value[1].toISOString(),
    })
    resetPreviewCount.value = result.tweet_count
  } catch (error) {
    console.error("重置预览失败:", error)
    ElMessage.error("查询失败")
  } finally {
    resetLoading.value = false
  }
}

/** 执行重置 */
async function handleResetExecute() {
  if (!resetDateRange.value) return
  resetTaskRunning.value = true
  try {
    const response = await summariesApi.startReset({
      since: resetDateRange.value[0].toISOString(),
      until: resetDateRange.value[1].toISOString(),
    })
    ElMessage.success(`重置任务已提交，共 ${response.tweet_count} 条推文`)
    resetDialogVisible.value = false

    pollingHandle = taskPollingService.startPolling(
      response.task_id,
      async () => await summariesApi.getTaskStatus(response.task_id) as TaskStatusResponse,
      () => {},
      () => {
        ElMessage.success("摘要重置完成")
        resetTaskRunning.value = false
        loadTweets()
      },
      (error) => {
        console.error("重置轮询失败:", error)
        resetTaskRunning.value = false
      },
    )
  } catch (error) {
    console.error("重置执行失败:", error)
    ElMessage.error("重置提交失败")
    resetTaskRunning.value = false
  }
}

/** 点击推文 */
function handleTweetClick(tweetId: string) {
  router.push(`/tweets/${tweetId}`)
}

/** 组件挂载时加载数据 */
onMounted(() => {
  loadTweets()
})

/** 组件卸载时清理轮询 */
onUnmounted(() => {
  if (pollingHandle) {
    pollingHandle.cancel()
    pollingHandle = null
  }
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

.batch-actions {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.selected-count {
  color: #409eff;
  font-size: 0.875rem;
  font-weight: 500;
}

.tweet-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.tweet-card-wrapper {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
}

.tweet-checkbox {
  margin-top: 1.1rem;
  flex-shrink: 0;
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
