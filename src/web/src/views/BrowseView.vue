<template>
  <div class="browse-view">
    <!-- 全屏模式下的工具条 -->
    <div v-if="isFullscreen" class="fullscreen-toolbar">
      <span class="fullscreen-title">推文浏览</span>
      <el-button text :icon="CloseBold" @click="exitFullscreen">退出全屏</el-button>
    </div>

    <div class="browse-layout" :class="{ 'browse-layout--fullscreen': isFullscreen }">
      <!-- 日历面板 -->
      <div class="calendar-panel">
        <el-calendar v-model="selectedDate" class="browse-calendar">
          <template #date-cell="{ data }">
            <div class="calendar-cell" :class="{ 'has-tweets': getDayCount(data.day) > 0 }">
              <span class="calendar-day">{{ data.day.split('-').slice(2).join('') }}</span>
              <el-badge
                v-if="getDayCount(data.day) > 0"
                :value="getDayCount(data.day)"
                :max="99"
                class="tweet-badge"
              />
            </div>
          </template>
        </el-calendar>
      </div>

      <!-- 作者列表面板 -->
      <div class="author-panel">
        <div class="panel-header">作者列表</div>
        <el-skeleton v-if="authorsLoading" :rows="5" animated />
        <div v-else class="author-list">
          <div
            class="author-item"
            :class="{ active: selectedAuthor === null }"
            @click="selectAuthor(null)"
          >
            <span class="author-name-text">全部作者</span>
            <el-badge :value="totalTweets" :max="999" type="info" />
          </div>
          <div
            v-for="author in authors"
            :key="author.author_username"
            class="author-item"
            :class="{ active: selectedAuthor === author.author_username }"
            @click="selectAuthor(author.author_username)"
          >
            <div class="author-info-block">
              <span class="author-display-name">{{ author.author_display_name || author.author_username }}</span>
              <span class="author-handle">@{{ author.author_username }}</span>
              <span v-if="author.reason" class="author-reason" :title="author.reason">{{ author.reason }}</span>
            </div>
            <el-badge :value="author.tweet_count" :max="99" />
          </div>
        </div>
      </div>

      <!-- 推文展示面板 -->
      <div class="tweet-panel">
        <!-- 选中作者时，顶部显示作者信息 -->
        <div v-if="selectedAuthorInfo" class="selected-author-header">
          <span class="selected-author-name">{{ selectedAuthorInfo.author_display_name || selectedAuthorInfo.author_username }}</span>
          <span class="selected-author-handle">@{{ selectedAuthorInfo.author_username }}</span>
          <span v-if="selectedAuthorInfo.reason" class="selected-author-reason">{{ selectedAuthorInfo.reason }}</span>
          <el-tag size="small" type="info">{{ selectedAuthorInfo.tweet_count }} 条推文</el-tag>
        </div>

        <el-skeleton v-if="tweetsLoading" :rows="8" animated />
        <el-empty v-else-if="tweets.length === 0" description="该日期暂无推文" />
        <div v-else class="tweet-list">
          <div v-for="tweet in tweets" :key="tweet.tweet_id" class="tweet-card">
            <!-- 发布时刻 -->
            <div class="tweet-time-row">
              <span class="tweet-time">{{ formatFullDateTime(tweet.created_at) }}</span>
              <!-- 日期模式：显示作者信息 -->
              <div v-if="!selectedAuthor" class="tweet-author-inline">
                <span class="inline-author-name">{{ tweet.author_display_name || tweet.author_username }}</span>
                <span class="inline-author-handle">@{{ tweet.author_username }}</span>
              </div>
            </div>

            <!-- 摘要 -->
            <div v-if="tweet.summary_text" class="tweet-section summary-section">
              <div class="section-label">摘要</div>
              <div class="section-content">{{ tweet.summary_text }}</div>
            </div>

            <!-- 中文翻译 -->
            <div v-if="tweet.translation_text" class="tweet-section translation-section">
              <div class="section-label">翻译</div>
              <div class="section-content">{{ tweet.translation_text }}</div>
            </div>

            <!-- 原文 -->
            <div class="tweet-section original-section">
              <div class="section-label">原文</div>
              <div class="section-content original-text">{{ tweet.text }}</div>
            </div>

            <!-- 媒体附件 -->
            <div v-if="tweet.media && tweet.media.length > 0" class="tweet-media">
              <img
                v-for="(media, index) in tweet.media"
                :key="index"
                :src="(media as any).url || (media as any).preview_image_url"
                :alt="`媒体 ${index + 1}`"
                class="media-image"
              />
            </div>

            <!-- 引用推文 -->
            <div v-if="tweet.referenced_tweet_id" class="referenced-tweet">
              <div class="ref-label">
                {{ getReferenceLabel(tweet.reference_type) }}
              </div>
              <div class="ref-content">
                <span class="ref-author">@{{ tweet.referenced_tweet_author_username }}</span>
                <span class="ref-text">{{ tweet.referenced_tweet_text }}</span>
              </div>
              <div v-if="tweet.referenced_tweet_media && tweet.referenced_tweet_media.length > 0" class="tweet-media ref-media">
                <img
                  v-for="(media, index) in tweet.referenced_tweet_media"
                  :key="index"
                  :src="(media as any).url || (media as any).preview_image_url"
                  :alt="`引用媒体 ${index + 1}`"
                  class="media-image"
                />
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
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, inject, onMounted, onUnmounted, type Ref } from "vue"
import { CloseBold } from "@element-plus/icons-vue"
import { browseApi } from "@/api"
import { formatFullDateTime } from "@/utils/format"
import type { AuthorInfo, BrowseTweetItem } from "@/types"

/** 全屏模式 */
const isFullscreen = inject<Ref<boolean>>("isFullscreen", ref(false))

function exitFullscreen() {
  isFullscreen.value = false
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === "Escape" && isFullscreen.value) {
    exitFullscreen()
  }
}

/** 选中日期 */
const selectedDate = ref(new Date())

/** 选中作者 */
const selectedAuthor = ref<string | null>(null)

/** 每日推文数量映射 */
const dailyCountMap = ref<Record<string, number>>({})

/** 作者列表 */
const authors = ref<AuthorInfo[]>([])

/** 推文列表 */
const tweets = ref<BrowseTweetItem[]>([])

/** 推文总数 */
const total = ref(0)

/** 当前页码 */
const page = ref(1)

/** 每页条数 */
const pageSize = 20

/** 加载状态 */
const authorsLoading = ref(false)
const tweetsLoading = ref(false)

/** 推文总数（用于"全部作者"badge） */
const totalTweets = computed(() => {
  return authors.value.reduce((sum, a) => sum + a.tweet_count, 0)
})

/** 当前年月字符串，用于检测月份切换 */
const currentYearMonth = computed(() => {
  const d = selectedDate.value
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`
})

/** 当前选中日期字符串 YYYY-MM-DD */
const selectedDateStr = computed(() => {
  const d = selectedDate.value
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, "0")
  const day = String(d.getDate()).padStart(2, "0")
  return `${y}-${m}-${day}`
})

/** 选中的作者详细信息 */
const selectedAuthorInfo = computed(() => {
  if (!selectedAuthor.value) return null
  return authors.value.find((a) => a.author_username === selectedAuthor.value) || null
})

/** 获取指定日期的推文数量 */
function getDayCount(day: string): number {
  return dailyCountMap.value[day] || 0
}

/** 获取引用类型标签 */
function getReferenceLabel(type: string | null): string {
  switch (type) {
    case "retweeted":
      return "转推"
    case "quoted":
      return "引用"
    case "replied_to":
      return "回复"
    default:
      return "引用"
  }
}

/** 加载每日统计 */
async function loadDailyStats() {
  const d = selectedDate.value
  try {
    const resp = await browseApi.getDailyStats(d.getFullYear(), d.getMonth() + 1)
    const map: Record<string, number> = {}
    for (const item of resp.days) {
      map[item.date] = item.count
    }
    dailyCountMap.value = map
  } catch (error) {
    console.error("加载每日统计失败:", error)
  }
}

/** 加载作者列表 */
async function loadAuthors() {
  authorsLoading.value = true
  try {
    const resp = await browseApi.getAuthors({ date: selectedDateStr.value })
    authors.value = resp.authors
  } catch (error) {
    console.error("加载作者列表失败:", error)
    authors.value = []
  } finally {
    authorsLoading.value = false
  }
}

/** 加载推文列表 */
async function loadTweets() {
  tweetsLoading.value = true
  try {
    const resp = await browseApi.getTweets({
      date: selectedDateStr.value,
      author: selectedAuthor.value || undefined,
      page: page.value,
      page_size: pageSize,
    })
    tweets.value = resp.items
    total.value = resp.total
  } catch (error) {
    console.error("加载推文列表失败:", error)
    tweets.value = []
    total.value = 0
  } finally {
    tweetsLoading.value = false
  }
}

/** 选择作者 */
function selectAuthor(username: string | null) {
  selectedAuthor.value = username
  page.value = 1
  loadTweets()
}

/** 翻页 */
function handlePageChange(newPage: number) {
  page.value = newPage
  loadTweets()
}

/** 监听月份切换 */
watch(currentYearMonth, () => {
  loadDailyStats()
})

/** 监听日期切换 */
watch(selectedDateStr, () => {
  selectedAuthor.value = null
  page.value = 1
  loadAuthors()
  loadTweets()
})

/** 初始加载 */
onMounted(() => {
  loadDailyStats()
  loadAuthors()
  loadTweets()
  document.addEventListener("keydown", handleKeydown)
})

onUnmounted(() => {
  document.removeEventListener("keydown", handleKeydown)
})
</script>

<style scoped>
.browse-view {
  height: 100%;
}

.browse-layout {
  display: flex;
  gap: 16px;
  height: calc(100vh - 100px);
}

.browse-layout--fullscreen {
  height: calc(100vh - 45px);
}

/* 全屏工具条 */
.fullscreen-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
}

.fullscreen-title {
  font-size: 15px;
  font-weight: 500;
  color: #303133;
}

/* 日历面板 */
.calendar-panel {
  width: 320px;
  flex-shrink: 0;
  overflow-y: auto;
}

.browse-calendar {
  --el-calendar-border: 1px solid #e4e7ed;
}

.browse-calendar :deep(.el-calendar__header) {
  padding: 8px 12px;
}

.browse-calendar :deep(.el-calendar__body) {
  padding: 0 8px 8px;
}

.browse-calendar :deep(.el-calendar-table .el-calendar-day) {
  height: 48px;
  padding: 2px;
}

.calendar-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  position: relative;
}

.calendar-cell.has-tweets {
  font-weight: 600;
}

.calendar-day {
  font-size: 13px;
}

.tweet-badge {
  position: absolute;
  top: -2px;
  right: -2px;
}

.tweet-badge :deep(.el-badge__content) {
  font-size: 10px;
  height: 16px;
  line-height: 16px;
  padding: 0 4px;
}

/* 作者面板 */
.author-panel {
  width: 240px;
  flex-shrink: 0;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  background: #fff;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel-header {
  padding: 12px 16px;
  font-weight: 600;
  font-size: 14px;
  border-bottom: 1px solid #e4e7ed;
  color: #303133;
}

.author-list {
  flex: 1;
  overflow-y: auto;
}

.author-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  cursor: pointer;
  transition: background-color 0.2s;
  border-bottom: 1px solid #f0f0f0;
}

.author-item:hover {
  background-color: #f5f7fa;
}

.author-item.active {
  background-color: #ecf5ff;
  color: #409eff;
}

.author-info-block {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
  margin-right: 8px;
}

.author-display-name {
  font-size: 13px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.author-handle {
  font-size: 11px;
  color: #909399;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.author-reason {
  font-size: 11px;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.author-name-text {
  font-size: 13px;
  font-weight: 500;
}

/* 推文面板 */
.tweet-panel {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

.selected-author-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  margin-bottom: 12px;
}

.selected-author-name {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.selected-author-handle {
  font-size: 13px;
  color: #909399;
}

.selected-author-reason {
  font-size: 13px;
  color: #303133;
}

.tweet-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.tweet-card {
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  padding: 16px;
}

.tweet-time-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #f0f0f0;
}

.tweet-time {
  font-size: 12px;
  color: #909399;
}

.tweet-author-inline {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.inline-author-name {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}

.inline-author-handle {
  font-size: 12px;
  color: #909399;
}

.tweet-section {
  margin-bottom: 10px;
}

.tweet-section:last-child {
  margin-bottom: 0;
}

.section-label {
  font-size: 11px;
  color: #909399;
  margin-bottom: 4px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.section-content {
  font-size: 14px;
  line-height: 1.7;
  color: #303133;
  white-space: pre-wrap;
  word-break: break-word;
}

.summary-section .section-content {
  background: #f0f9eb;
  padding: 8px 12px;
  border-radius: 4px;
  border-left: 3px solid #67c23a;
}

.translation-section .section-content {
  background: #ecf5ff;
  padding: 8px 12px;
  border-radius: 4px;
  border-left: 3px solid #409eff;
}

.original-text {
  color: #606266;
}

.tweet-media {
  margin-top: 8px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 8px;
}

.media-image {
  width: 100%;
  border-radius: 4px;
  object-fit: cover;
  max-height: 200px;
}

.referenced-tweet {
  margin-top: 10px;
  padding: 10px 12px;
  background: #fafafa;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
}

.ref-label {
  font-size: 11px;
  color: #909399;
  margin-bottom: 4px;
}

.ref-content {
  font-size: 13px;
  line-height: 1.6;
  color: #606266;
}

.ref-author {
  font-weight: 500;
  color: #409eff;
  margin-right: 6px;
}

.ref-text {
  white-space: pre-wrap;
  word-break: break-word;
}

.ref-media {
  margin-top: 6px;
}

.pagination-bar {
  display: flex;
  justify-content: center;
  padding: 16px 0;
  margin-top: auto;
}
</style>
