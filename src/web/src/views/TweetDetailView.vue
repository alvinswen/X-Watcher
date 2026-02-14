<template>
  <div class="tweet-detail-view">
    <!-- 返回按钮 -->
    <el-button :icon="ArrowLeft" @click="handleGoBack" class="back-button">
      返回
    </el-button>

    <!-- 加载状态 -->
    <el-skeleton v-if="loading" :rows="8" animated />

    <!-- 推文详情 -->
    <div v-else-if="tweet" class="tweet-detail">
      <!-- 推文卡片 -->
      <el-card class="tweet-card">
        <div class="tweet-header">
          <div class="author-info">
            <span class="author-name">{{ tweet.author_display_name || tweet.author_username }}</span>
            <span class="author-username">@{{ tweet.author_username }}</span>
          </div>
          <span class="tweet-time">{{ formatFullDateTime(tweet.created_at) }}</span>
        </div>
        <div class="tweet-content">{{ tweet.text }}</div>
        <div v-if="tweet.media && tweet.media.length > 0" class="tweet-media">
          <img
            v-for="(media, index) in tweet.media"
            :key="index"
            :src="media.url || (media as any).preview_image_url"
            :alt="`媒体 ${index + 1}`"
            class="media-image"
          />
        </div>
      </el-card>

      <!-- AI 摘要卡片 -->
      <el-card v-if="tweet.summary" class="summary-card">
        <template #header>
          <div class="card-header">
            <div class="card-header-left">
              <span>AI 摘要</span>
              <el-tag v-if="tweet.summary.cached" type="info" size="small">缓存</el-tag>
            </div>
            <el-button
              link
              :icon="Refresh"
              :loading="regenerating"
              :disabled="regenerating"
              @click="handleRegenerateSummary"
            >
              重新生成
            </el-button>
          </div>
        </template>
        <div class="summary-content">
          <p class="summary-text">{{ tweet.summary.summary_text }}</p>
          <p v-if="tweet.summary.translation_text" class="summary-translation">
            <strong>中文翻译：</strong>{{ tweet.summary.translation_text }}
          </p>
        </div>
        <el-descriptions :column="2" size="small" border class="summary-meta">
          <el-descriptions-item label="模型">
            {{ tweet.summary.model_provider }} / {{ tweet.summary.model_name }}
          </el-descriptions-item>
          <el-descriptions-item label="成本">
            ${{ tweet.summary.cost_usd.toFixed(6) }}
          </el-descriptions-item>
          <el-descriptions-item label="生成方式" :span="2">
            {{ tweet.summary.is_generated_summary ? "生成摘要" : "原文" }}
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- 无摘要提示 -->
      <el-card v-else class="info-card">
        <el-empty description="此推文暂无摘要" :image-size="80">
          <el-button
            type="primary"
            :icon="Refresh"
            :loading="regenerating"
            :disabled="regenerating"
            @click="handleRegenerateSummary"
          >
            生成摘要
          </el-button>
        </el-empty>
      </el-card>

      <!-- 去重信息卡片 -->
      <el-card v-if="tweet.deduplication" class="deduplication-card">
        <template #header>
          <span>去重信息</span>
        </template>
        <el-descriptions :column="2" size="small" border>
          <el-descriptions-item label="去重组 ID">
            {{ tweet.deduplication.group_id }}
          </el-descriptions-item>
          <el-descriptions-item label="去重类型">
            <el-tag :type="tweet.deduplication.deduplication_type === 'exact_duplicate' ? 'danger' : 'warning'" size="small">
              {{ tweet.deduplication.deduplication_type === 'exact_duplicate' ? '完全重复' : '相似内容' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="相似度" v-if="tweet.deduplication.similarity_score !== null">
            {{ (tweet.deduplication.similarity_score * 100).toFixed(1) }}%
          </el-descriptions-item>
          <el-descriptions-item label="包含推文数">
            {{ tweet.deduplication.tweet_ids?.length || 0 }}
          </el-descriptions-item>
        </el-descriptions>
      </el-card>
    </div>

    <!-- 错误状态 -->
    <el-result v-else icon="error" title="加载失败" sub-title="推文不存在或已被删除">
      <template #extra>
        <el-button type="primary" @click="handleGoBack">返回列表</el-button>
      </template>
    </el-result>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from "vue"
import { useRoute, useRouter } from "vue-router"
import { ArrowLeft, Refresh } from "@element-plus/icons-vue"
import { ElMessage } from "element-plus"
import { tweetsApi, summariesApi } from "@/api"
import { formatFullDateTime } from "@/utils/format"
import type { TweetDetail } from "@/types"

/** 路由实例 */
const route = useRoute()
const router = useRouter()

/** 推文详情 */
const tweet = ref<TweetDetail | null>(null)

/** 加载状态 */
const loading = ref(false)

/** 摘要再生成状态 */
const regenerating = ref(false)

/** 加载推文详情 */
async function loadTweetDetail() {
  const tweetId = route.params.id as string
  if (!tweetId) return

  loading.value = true
  try {
    tweet.value = await tweetsApi.getDetail(tweetId)
  } catch (error) {
    // 错误已被 API 拦截器处理
    console.error("加载推文详情失败:", error)
    tweet.value = null
  } finally {
    loading.value = false
  }
}

/** 返回上一页 */
function handleGoBack() {
  router.back()
}

/** 重新生成/生成摘要 */
async function handleRegenerateSummary() {
  const tweetId = route.params.id as string
  if (!tweetId) return

  regenerating.value = true
  try {
    await summariesApi.regenerate(tweetId)
    ElMessage.success("摘要生成成功")
    // 刷新详情
    tweet.value = await tweetsApi.getDetail(tweetId)
  } catch (error) {
    console.error("摘要生成失败:", error)
    ElMessage.error("摘要生成失败，请稍后重试")
  } finally {
    regenerating.value = false
  }
}

/** 组件挂载时加载数据 */
onMounted(() => {
  loadTweetDetail()
})
</script>

<style scoped>
.tweet-detail-view {
  max-width: 900px;
  margin: 0 auto;
}

.back-button {
  margin-bottom: 1rem;
}

.tweet-detail {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.tweet-card {
  border-radius: 8px;
}

.tweet-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 0.75rem;
  margin-bottom: 0.75rem;
  border-bottom: 1px solid #ebeef5;
}

.author-info {
  display: flex;
  align-items: baseline;
  gap: 0.75rem;
}

.author-name {
  font-weight: 600;
  font-size: 1.125rem;
  color: #333;
}

.author-username {
  color: #666;
  font-size: 0.875rem;
}

.tweet-time {
  color: #999;
  font-size: 0.875rem;
  margin-left: 1.5rem;
  white-space: nowrap;
}

.tweet-content {
  color: #333;
  line-height: 1.8;
  font-size: 1rem;
  white-space: pre-wrap;
  word-break: break-word;
}

.tweet-media {
  margin-top: 1rem;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 0.5rem;
}

.media-image {
  width: 100%;
  border-radius: 8px;
  object-fit: cover;
}

.summary-card,
.deduplication-card,
.info-card {
  border-radius: 8px;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-header-left {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.summary-content {
  margin-bottom: 1rem;
}

.summary-text {
  color: #333;
  line-height: 1.8;
  margin: 0 0 1rem 0;
}

.summary-translation {
  color: #666;
  line-height: 1.8;
  margin: 0;
  padding: 0.75rem;
  background-color: #f5f7fa;
  border-radius: 4px;
}

.summary-meta {
  margin-top: 0.5rem;
}

.info-card :deep(.el-empty) {
  padding: 1rem 0;
}
</style>
