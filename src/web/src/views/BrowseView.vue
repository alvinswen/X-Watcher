<template>
  <ApiKeyGuideEmpty v-if="needsApiKey" />
  <div v-else class="browse-view" data-testid="browse-view">
    <Teleport to="#header-toolbar-outlet" defer>
      <div v-show="!isFullscreen" class="header-toolbar">
        <el-switch
          v-model="longTweetFilterEnabled"
          active-text="长推"
          size="small"
          style="margin-right: 8px"
          data-testid="browse-long-tweet-filter"
        />
        <el-input-number
          v-if="longTweetFilterEnabled"
          v-model="longTweetMinLength"
          :min="1"
          :step="50"
          size="small"
          style="width: 130px; margin-right: 12px"
          :prefix-icon="undefined"
          controls-position="right"
        >
          <template #prefix>≥</template>
        </el-input-number>
        <el-button
          text
          :icon="FullScreen"
          data-testid="browse-fullscreen-toggle"
          @click="isFullscreen = true"
        >
          全屏
        </el-button>
      </div>
    </Teleport>

    <!-- 全屏模式下的工具条 -->
    <div v-if="isFullscreen" class="fullscreen-toolbar">
      <span class="fullscreen-title">{{ mode === 'timeline' ? `${timelineAuthorInfo?.author_display_name || timelineAuthor} 的时间线` : '推文浏览' }}</span>
      <span class="fullscreen-spacer"></span>
      <el-switch
        v-model="longTweetFilterEnabled"
        active-text="长推"
        size="small"
        style="margin-right: 8px;"
      />
      <el-input-number
        v-if="longTweetFilterEnabled"
        v-model="longTweetMinLength"
        :min="1"
        :step="50"
        size="small"
        style="width: 130px; margin-right: 12px;"
        controls-position="right"
      />
      <el-button
        text
        :icon="CloseBold"
        data-testid="browse-fullscreen-exit"
        @click="exitFullscreen"
      >
        退出全屏
      </el-button>
    </div>

    <div class="browse-layout" :class="{ 'browse-layout--fullscreen': isFullscreen }">
      <!-- ===== 日期浏览模式：日历 + 作者列表 ===== -->
      <template v-if="mode === 'date'">
        <CalendarPanel v-model="selectedDate" :daily-counts="dailyCountMap" />
        <AuthorPanel
          :authors="authors"
          :loading="authorsLoading"
          :selected-author="selectedAuthor"
          :total-tweets="totalTweets"
          @select="selectAuthor"
          @timeline="enterTimelineMode"
        />
      </template>

      <!-- ===== 作者时间线模式：侧边栏 ===== -->
      <TimelineControls
        v-else
        :author="timelineAuthor"
        :author-info="timelineAuthorInfo"
        :presets="timelinePresets"
        :active-preset="activeTimelinePreset"
        :date-range="timelineDateRange"
        :total="timelineTotal"
        @back="exitTimelineMode"
        @preset="applyPreset"
        @update:date-range="timelineDateRange = $event"
        @range-change="handleTimelineRangeChange"
      />

      <!-- 推文展示面板 -->
      <div class="tweet-panel" data-testid="browse-tweet-panel">
        <!-- 日期模式：选中作者时显示作者信息，全部作者时显示日期+总数 -->
        <div v-if="mode === 'date' && selectedAuthorInfo" class="selected-author-header">
          <span class="selected-author-name">{{ selectedAuthorInfo.author_display_name || selectedAuthorInfo.author_username }}</span>
          <span class="selected-author-handle">@{{ selectedAuthorInfo.author_username }}</span>
          <span v-if="selectedAuthorInfo.reason" class="selected-author-reason">{{ selectedAuthorInfo.reason }}</span>
          <el-tag size="small" type="info">{{ selectedAuthorInfo.tweet_count }} 条推文</el-tag>
          <el-button text size="small" @click="enterTimelineMode(selectedAuthorInfo.author_username)">
            <el-icon :size="14"><User /></el-icon> 全部推文
          </el-button>
        </div>
        <div v-else-if="mode === 'date' && !selectedAuthor" class="selected-author-header">
          <span class="selected-author-name">全部作者</span>
          <el-tag size="small" type="info">{{ totalTweets }} 条推文</el-tag>
        </div>

        <el-skeleton v-if="activeTweetsLoading" :rows="8" animated />
        <LoadErrorState
          v-else-if="activeTweetsLoadError"
          :retry="retryActiveTweets"
        />
        <el-empty v-else-if="activeTweets.length === 0" :description="mode === 'timeline' ? '该时间段暂无推文' : '该日期暂无推文'" />
        <div v-else class="tweet-list">
          <TweetCard
            v-for="(tweet, tweetIndex) in activeTweets"
            :key="tweet.tweet_id"
            :tweet="tweet"
            :show-author="mode === 'date' && !selectedAuthor"
            collapsible-original
            show-share
            :animation-index="tweetIndex"
            media-hover-zoom
            @share="handleShareTweet"
          />
        </div>

        <!-- 分页 -->
        <div v-if="!activeTweetsLoadError && activeTotal > 0" class="pagination-bar">
          <el-pagination
            v-model:current-page="activePage"
            :page-size="pageSize"
            :total="activeTotal"
            layout="total, prev, pager, next"
            data-testid="browse-pagination"
            @current-change="handleActivePageChange"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from "vue"
import { storeToRefs } from "pinia"
import { useRoute, useRouter } from "vue-router"
import { User, CloseBold, FullScreen } from "@element-plus/icons-vue"
import { ElMessage } from "element-plus"
import { browseApi, followsApi } from "@/api"
import ApiKeyGuideEmpty from "@/components/ApiKeyGuideEmpty.vue"
import LoadErrorState from "@/components/LoadErrorState.vue"
import TweetCard from "@/components/TweetCard.vue"
import AuthorPanel from "@/views/browse/AuthorPanel.vue"
import CalendarPanel from "@/views/browse/CalendarPanel.vue"
import TimelineControls from "@/views/browse/TimelineControls.vue"
import { useApiKeyGuard } from "@/composables/useApiKeyGuard"
import { useLayoutStore } from "@/stores/layout"
import { formatChineseDateTime } from "@/utils/format"
import type { AuthorInfo, BrowseTweetItem, TweetCardData, XUserProfile } from "@/types"

const route = useRoute()
const router = useRouter()

const layoutStore = useLayoutStore()
const {
  isFullscreen,
  longTweetFilterEnabled,
  longTweetMinLength,
} = storeToRefs(layoutStore)

const effectiveMinTextLength = computed(() => {
  return longTweetFilterEnabled.value ? longTweetMinLength.value : undefined
})

function exitFullscreen() {
  isFullscreen.value = false
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === "Escape" && isFullscreen.value) {
    exitFullscreen()
  }
}

/** 日期格式化 YYYY-MM-DD */
function formatDateStr(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, "0")
  const day = String(d.getDate()).padStart(2, "0")
  return `${y}-${m}-${day}`
}

function addDays(d: Date, n: number): Date {
  const result = new Date(d)
  result.setDate(result.getDate() + n)
  return result
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
const tweetsLoadError = ref(false)

/** ===== 时间线模式状态 ===== */
type BrowseMode = "date" | "timeline"
const mode = ref<BrowseMode>("date")

const timelineAuthor = ref<string | null>(null)
const timelineAuthorInfo = ref<Pick<AuthorInfo, "author_username" | "author_display_name" | "reason"> | null>(null)
const timelineDateRange = ref<[Date, Date]>([
  new Date(Date.now() - 7 * 86400000),
  new Date(),
])
const timelineTweets = ref<BrowseTweetItem[]>([])
const timelineTotal = ref(0)
const timelinePage = ref(1)
const timelineLoading = ref(false)
const timelineLoadError = ref(false)

const timelinePresets: { label: string; days: number | null }[] = [
  { label: "1周", days: 7 },
  { label: "2周", days: 14 },
  { label: "1月", days: 30 },
  { label: "全部", days: null },
]
const activeTimelinePreset = computed(
  () => timelinePresets.find((preset) => isPresetActive(preset.days))?.days,
)

/** 代理 computed：统一两种模式的数据源 */
const activeTweets = computed(() => mode.value === "timeline" ? timelineTweets.value : tweets.value)
const activeTotal = computed(() => mode.value === "timeline" ? timelineTotal.value : total.value)
const activeTweetsLoading = computed(() => mode.value === "timeline" ? timelineLoading.value : tweetsLoading.value)
const activeTweetsLoadError = computed(() => (
  mode.value === "timeline" ? timelineLoadError.value : tweetsLoadError.value
))
const activePage = computed({
  get: () => mode.value === "timeline" ? timelinePage.value : page.value,
  set: (val: number) => {
    if (mode.value === "timeline") timelinePage.value = val
    else page.value = val
  },
})

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
const selectedDateStr = computed(() => formatDateStr(selectedDate.value))

/** 选中的作者详细信息 */
const selectedAuthorInfo = computed(() => {
  if (!selectedAuthor.value) return null
  return authors.value.find((a) => a.author_username === selectedAuthor.value) || null
})

/** 根据用户名查找作者介绍 */
function findAuthorReason(username: string): string | null {
  const author = authors.value.find((a) => a.author_username === username)
  return author?.reason || null
}

/** 构建人物介绍段落 */
function buildProfileIntro(
  tweet: TweetCardData,
  profile: XUserProfile | null,
  reason: string | null,
): string {
  const displayName = profile?.display_name || tweet.author_display_name || tweet.author_username
  const username = tweet.author_username
  const parts: string[] = []

  parts.push(`## ${displayName}（@${username}）`)

  if (reason) {
    parts.push(reason)
  }

  if (profile?.description) {
    const statsItems: string[] = []
    if (profile.followers_count != null) statsItems.push(`粉丝 ${profile.followers_count.toLocaleString()}`)
    if (profile.following_count != null) statsItems.push(`关注 ${profile.following_count.toLocaleString()}`)
    if (profile.statuses_count != null) statsItems.push(`推文 ${profile.statuses_count.toLocaleString()}`)

    let quote = `> ${profile.description}`
    if (statsItems.length > 0) {
      quote += `\n>\n> ${statsItems.join(" · ")}`
    }
    parts.push(quote)
  }

  return parts.join("\n\n")
}

/** 生成推文分享 Markdown 内容 */
function buildShareMarkdown(
  tweet: TweetCardData,
  profile: XUserProfile | null,
  reason: string | null,
): string {
  const sections: string[] = []

  // 1. 人物介绍
  sections.push(buildProfileIntro(tweet, profile, reason))

  // 分隔线
  sections.push("---")

  // 2. 发布时间
  const timeStr = formatChineseDateTime(tweet.created_at)
  sections.push(`**发布时间**：${timeStr}`)

  // 3. 翻译
  if (tweet.translation_text) {
    sections.push(`### 翻译\n\n${tweet.translation_text}`)
  }

  // 4. 原文
  sections.push(`### 原文\n\n${tweet.text}`)

  // 5. 摘要
  if (tweet.summary_text) {
    sections.push(`### 摘要\n\n${tweet.summary_text}`)
  }

  return sections.join("\n\n")
}

/** 分享推文：生成 Markdown 并复制到剪贴板 */
async function handleShareTweet(tweet: TweetCardData) {
  const reason = findAuthorReason(tweet.author_username)

  // 尝试获取完整档案，失败时降级
  let profile: XUserProfile | null = null
  try {
    profile = await followsApi.getProfile(tweet.author_username)
  } catch {
    // 档案获取失败，使用已有数据降级
  }

  try {
    const markdown = buildShareMarkdown(tweet, profile, reason)
    await navigator.clipboard.writeText(markdown)
    ElMessage.success("已复制到剪贴板")
  } catch {
    ElMessage.error("复制失败，请手动复制")
  }
}

/** 加载每日统计 */
async function loadDailyStats() {
  const d = selectedDate.value
  try {
    const resp = await browseApi.getDailyStats(d.getFullYear(), d.getMonth() + 1, effectiveMinTextLength.value)
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
    const resp = await browseApi.getAuthors({ date: selectedDateStr.value, min_text_length: effectiveMinTextLength.value })
    authors.value = resp.authors
  } catch (error) {
    console.error("加载作者列表失败:", error)
    authors.value = []
  } finally {
    authorsLoading.value = false
  }
}

/** 加载推文列表 */
async function loadTweets(preserveError = false) {
  tweetsLoading.value = !preserveError
  if (!preserveError) {
    tweetsLoadError.value = false
  }
  try {
    const resp = await browseApi.getTweets({
      date: selectedDateStr.value,
      author: selectedAuthor.value || undefined,
      page: page.value,
      page_size: pageSize,
      min_text_length: effectiveMinTextLength.value,
    })
    tweets.value = resp.items
    total.value = resp.total
    tweetsLoadError.value = false
  } catch (error) {
    console.error("加载推文列表失败:", error)
    tweets.value = []
    total.value = 0
    tweetsLoadError.value = true
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
function handleActivePageChange(newPage: number) {
  if (mode.value === "timeline") {
    timelinePage.value = newPage
    syncTimelineToUrl()
    loadTimelineTweets()
  } else {
    page.value = newPage
    loadTweets()
  }
}

/** ===== 时间线模式函数 ===== */

/** 进入时间线模式 */
function enterTimelineMode(username: string) {
  const authorInfo = authors.value.find((a) => a.author_username === username)
  mode.value = "timeline"
  timelineAuthor.value = username
  timelineAuthorInfo.value = authorInfo
    ? {
        author_username: authorInfo.author_username,
        author_display_name: authorInfo.author_display_name,
        reason: authorInfo.reason,
      }
    : null
  const now = new Date()
  const weekAgo = new Date(now.getTime() - 7 * 86400000)
  timelineDateRange.value = [weekAgo, now]
  timelinePage.value = 1
  syncTimelineToUrl()
  loadTimelineTweets()
}

/** 退出时间线模式 */
function exitTimelineMode() {
  mode.value = "date"
  timelineAuthor.value = null
  timelineAuthorInfo.value = null
  router.replace({ query: {} })
  selectedAuthor.value = null
  page.value = 1
  loadDailyStats()
  loadAuthors()
  loadTweets()
}

/** 加载时间线推文 */
async function loadTimelineTweets(preserveError = false) {
  if (!timelineAuthor.value || !timelineDateRange.value) return
  timelineLoading.value = !preserveError
  if (!preserveError) {
    timelineLoadError.value = false
  }
  try {
    const [since, until] = timelineDateRange.value
    const resp = await browseApi.getAuthorTimeline({
      author: timelineAuthor.value,
      since: formatDateStr(since),
      until: formatDateStr(addDays(until, 1)),
      page: timelinePage.value,
      page_size: pageSize,
      min_text_length: effectiveMinTextLength.value,
    })
    timelineTweets.value = resp.items
    timelineTotal.value = resp.total
    timelineLoadError.value = false
    if (!timelineAuthorInfo.value) {
      timelineAuthorInfo.value = {
        author_username: resp.author_username,
        author_display_name: resp.author_display_name,
        reason: resp.reason,
      }
    }
  } catch (error) {
    console.error("加载时间线推文失败:", error)
    timelineTweets.value = []
    timelineTotal.value = 0
    timelineLoadError.value = true
  } finally {
    timelineLoading.value = false
  }
}

function retryActiveTweets() {
  return mode.value === "timeline"
    ? loadTimelineTweets(true)
    : loadTweets(true)
}

/** 应用预设时间范围 */
function applyPreset(days: number | null) {
  const now = new Date()
  const start = days === null ? new Date(2006, 2, 21) : new Date(now.getTime() - days * 86400000)
  timelineDateRange.value = [start, now]
  timelinePage.value = 1
  syncTimelineToUrl()
  loadTimelineTweets()
}

/** 检测当前是否匹配某个预设 */
function isPresetActive(days: number | null): boolean {
  if (!timelineDateRange.value) return false
  const [since, until] = timelineDateRange.value
  const diff = Math.round((until.getTime() - since.getTime()) / 86400000)
  const isUntilToday = formatDateStr(until) === formatDateStr(new Date())
  if (days === null) return since.getFullYear() <= 2006 && isUntilToday
  return diff === days && isUntilToday
}

/** 自定义日期范围变更 */
function handleTimelineRangeChange() {
  timelinePage.value = 1
  syncTimelineToUrl()
  loadTimelineTweets()
}

/** 同步时间线状态到 URL */
function syncTimelineToUrl() {
  if (mode.value !== "timeline" || !timelineAuthor.value) return
  const query: Record<string, string> = {
    author: timelineAuthor.value,
  }
  if (timelineDateRange.value) {
    const diffDays = Math.round(
      (timelineDateRange.value[1].getTime() - timelineDateRange.value[0].getTime()) / 86400000,
    )
    query.days = String(diffDays)
  }
  if (timelinePage.value > 1) {
    query.page = String(timelinePage.value)
  }
  router.replace({ query })
}

/** 监听长推文过滤变化 */
watch(effectiveMinTextLength, () => {
  if (mode.value === "timeline") {
    timelinePage.value = 1
    loadTimelineTweets()
  } else {
    selectedAuthor.value = null
    page.value = 1
    loadDailyStats()
    loadAuthors()
    loadTweets()
  }
})

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
function initializeBrowse() {
  const authorParam = route.query.author as string
  if (authorParam) {
    mode.value = "timeline"
    timelineAuthor.value = authorParam
    const daysParam = parseInt(route.query.days as string) || 7
    const pageParam = parseInt(route.query.page as string) || 1
    const now = new Date()
    const start = new Date(now.getTime() - daysParam * 86400000)
    timelineDateRange.value = [start, now]
    timelinePage.value = pageParam
    loadTimelineTweets()
  } else {
    loadDailyStats()
    loadAuthors()
    loadTweets()
  }
  document.addEventListener("keydown", handleKeydown)
}

const { needsApiKey } = useApiKeyGuard(initializeBrowse)

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
  padding: 8px 16px;
  background: var(--bg-card);
  border-bottom: 1px solid var(--border-light);
}

.fullscreen-spacer {
  flex: 1;
}

.fullscreen-title {
  font-size: 15px;
  font-weight: 500;
  color: var(--text-primary);
  font-family: var(--font-reading);
}

.header-toolbar {
  display: flex;
  align-items: center;
}

/* ========== 推文面板 ========== */
.tweet-panel {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  padding-right: 8px;
}

.selected-author-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 20px;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--card-radius);
  margin-bottom: 16px;
}

.selected-author-name {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  font-family: var(--font-reading);
}

.selected-author-handle {
  font-size: var(--small-font-size);
  color: var(--text-tertiary);
  font-family: var(--font-mono);
}

.selected-author-reason {
  font-size: var(--small-font-size);
  color: var(--text-secondary);
}

/* ========== 推文列表 ========== */
.tweet-list {
  display: flex;
  flex-direction: column;
  gap: var(--card-gap);
  max-width: 720px;
}

/* ---- 分页 ---- */
.pagination-bar {
  display: flex;
  justify-content: center;
  padding: 20px 0;
  margin-top: auto;
}

</style>
