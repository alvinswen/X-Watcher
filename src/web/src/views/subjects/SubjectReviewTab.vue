<script setup lang="ts">
import { computed } from "vue"
import { Document, Refresh, WarningFilled } from "@element-plus/icons-vue"
import type { SubjectReview, SubjectReviewSection } from "@/types"

const props = defineProps<{
  loading: boolean
  review: SubjectReview | null
  version: number
  sections: SubjectReviewSection[]
  hasTrend: boolean
  error: string
  pending: boolean
  refreshing: boolean
  requestButtonText: string
  updatedText: string
  openSections: string[]
  openCites: string[]
}>()

const emit = defineEmits<{
  request: []
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

function reviewSectionName(index: number): string {
  return String(index)
}

function reviewCiteName(index: number): string {
  return `cite-${index}`
}
</script>

<template>
  <div v-if="loading && !review" class="review-pane">
    <el-skeleton v-for="index in 2" :key="index" animated class="review-skeleton">
      <template #template>
        <el-skeleton-item variant="text" class="review-skel-title" />
        <el-skeleton-item variant="text" />
        <el-skeleton-item variant="text" />
      </template>
    </el-skeleton>
  </div>

  <div v-else class="review-pane" :data-review-version="version">
    <div v-if="error" class="review-error" data-review-error>
      <el-icon><WarningFilled /></el-icon>
      <p>{{ error }}</p>
      <el-button plain :icon="Refresh" @click="$emit('request')">重试</el-button>
    </div>

    <template v-else>
      <div class="review-infobar">
        <div class="review-info-left">
          <span
            class="review-version-badge"
            :class="{ empty: version === 0 }"
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
        <template #image><el-icon><Document /></el-icon></template>
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

            <p class="review-section-body">{{ section.body }}</p>

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
                  class="review-cite-item"
                  :data-cited-tweet-ids="section.cited_tweet_ids.join(',')"
                >
                  <p>{{ section.body }}</p>
                  <div class="review-cite-ids">
                    <code v-for="tweetId in section.cited_tweet_ids" :key="tweetId">
                      {{ tweetId }}
                    </code>
                  </div>
                </div>
              </el-collapse-item>
            </el-collapse>
          </el-collapse-item>
        </el-collapse>
      </template>
    </template>
  </div>
</template>
