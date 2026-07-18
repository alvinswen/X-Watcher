<script setup lang="ts">
import { computed, nextTick, reactive, ref } from "vue"
import type { FormInstance, FormRules } from "element-plus"
import { ElMessage, ElMessageBox } from "element-plus"
import {
  Clock,
  EditPen,
  Plus,
  WarningFilled,
} from "@element-plus/icons-vue"
import { subjectsApi } from "@/api/subjects"
import { ApiRequestError } from "@/api/client"
import ApiKeyGuideEmpty from "@/components/ApiKeyGuideEmpty.vue"
import { useApiKeyGuard } from "@/composables/useApiKeyGuard"
import { formatRelativeTime } from "@/utils/format"
import SubjectDigestTab from "@/views/subjects/SubjectDigestTab.vue"
import SubjectFeedTab from "@/views/subjects/SubjectFeedTab.vue"
import SubjectFormDrawer from "@/views/subjects/SubjectFormDrawer.vue"
import SubjectListPanel from "@/views/subjects/SubjectListPanel.vue"
import SubjectReviewTab from "@/views/subjects/SubjectReviewTab.vue"
import { formatAbsoluteDateTime } from "@/views/subjects/subjectFormat"
import type {
  Subject,
  SubjectDigest,
  SubjectFeedItem,
  SubjectReview,
  SubjectStatus,
} from "@/types"

interface SubjectForm {
  name: string
  nl_description: string
  keywords: string[]
  status: SubjectStatus
}

type ClassifyHintState = "recent" | "stale" | "never" | "empty"

const STALE_THRESHOLD_MS = 6 * 3_600_000
const REVIEW_PENDING_KEY_PREFIX = "subject-review-pending:"

const subjects = ref<Subject[]>([])
const selectedId = ref<string | null>(null)
const feedItems = ref<SubjectFeedItem[]>([])
const digests = ref<SubjectDigest[]>([])
const review = ref<SubjectReview | null>(null)
const lastClassifiedAt = ref<string | null>(null)
const activeTab = ref<"feed" | "digest" | "review">("feed")
const statusFilter = ref<"all" | SubjectStatus>("all")
const loadingSubjects = ref(false)
const loadingDetail = ref(false)
const reviewRefreshing = ref(false)
const reviewPending = ref(false)
const reviewError = ref("")
const reviewOpenSections = ref<string[]>([])
const reviewOpenCites = ref<string[]>([])
const sessionPendingReviews = ref<Record<string, number>>({})
const pageError = ref("")
const createError = ref("")
const permissionError = ref(false)
const drawerVisible = ref(false)
const drawerMode = ref<"create" | "edit">("create")
const submitting = ref(false)
const keywordInput = ref("")
const formRef = ref<FormInstance>()
const detailScroll = ref<HTMLElement>()

const form = reactive<SubjectForm>({
  name: "",
  nl_description: "",
  keywords: [],
  status: "active",
})

const rules = reactive<FormRules<SubjectForm>>({
  name: [{ required: true, message: "议题名必填", trigger: "blur" }],
  nl_description: [{ required: true, message: "语义描述必填", trigger: "blur" }],
})

const activeCount = computed(() => subjects.value.filter((item) => item.status === "active").length)
const activeLimitReached = computed(() => activeCount.value >= 20)
const filteredSubjects = computed(() => {
  if (statusFilter.value === "all") {
    return subjects.value
  }
  return subjects.value.filter((item) => item.status === statusFilter.value)
})
const selectedSubject = computed(() => subjects.value.find((item) => item.subject_id === selectedId.value) || null)
const drawerTitle = computed(() => (drawerMode.value === "create" ? "新建议题" : "编辑议题"))
const reviewVersion = computed(() => review.value?.version ?? 0)
const reviewSections = computed(() => review.value?.sections ?? [])
const reviewHasTrend = computed(() => {
  const trend = review.value?.trend
  return reviewVersion.value >= 2 && Boolean(trend?.emerging.length || trend?.fading.length)
})
const classifyHintState = computed<ClassifyHintState>(() => {
  if (!selectedSubject.value) {
    return "empty"
  }
  if (!lastClassifiedAt.value) {
    return "never"
  }
  const timestamp = new Date(lastClassifiedAt.value).getTime()
  if (Number.isNaN(timestamp)) {
    return "never"
  }
  return Date.now() - timestamp > STALE_THRESHOLD_MS ? "stale" : "recent"
})
const classifyHintIcon = computed(() => (classifyHintState.value === "never" ? WarningFilled : Clock))
const classifyHintPrefix = computed(() => (
  classifyHintState.value === "stale" ? "距上次分类已较久：" : "最近一次分类："
))
const classifyHintRelativeText = computed(
  () => formatRelativeTime(lastClassifiedAt.value, "尚无更新"),
)
const classifyHintText = computed(() => {
  if (classifyHintState.value === "empty") {
    return "选择议题后查看最近一次分类时间"
  }
  if (classifyHintState.value === "never") {
    return "尚未分类，等待外部分类节拍命中"
  }
  return ""
})
const classifyHintTitle = computed(() => (lastClassifiedAt.value ? formatAbsoluteDateTime(lastClassifiedAt.value) : ""))
const reviewRequestButtonText = computed(() => (reviewPending.value ? "已请求·待处理" : "请求更新综述"))

const { needsApiKey } = useApiKeyGuard(loadSubjects)

async function loadSubjects(preferId?: string) {
  loadingSubjects.value = true
  pageError.value = ""
  permissionError.value = false
  try {
    subjects.value = await subjectsApi.list()
    const nextId = preferId || selectedId.value
    if (nextId && subjects.value.some((item) => item.subject_id === nextId)) {
      selectedId.value = nextId
    } else {
      selectedId.value = subjects.value[0]?.subject_id || null
    }
    await loadSelectedData()
  } catch (error) {
    const message = error instanceof Error ? error.message : "议题加载失败"
    permissionError.value = error instanceof ApiRequestError && error.status === 403
    pageError.value = permissionError.value ? "" : message
  } finally {
    loadingSubjects.value = false
  }
}

async function loadSelectedData() {
  if (!selectedId.value) {
    feedItems.value = []
    digests.value = []
    review.value = null
    lastClassifiedAt.value = null
    reviewError.value = ""
    reviewPending.value = false
    return
  }
  loadingDetail.value = true
  try {
    const [feed, digestResponse] = await Promise.all([
      subjectsApi.feed(selectedId.value),
      subjectsApi.digests(selectedId.value),
    ])
    feedItems.value = feed.items
    lastClassifiedAt.value = feed.last_classified_at ?? null
    digests.value = digestResponse.items
    await loadReviewOnly()
  } catch (error) {
    pageError.value = error instanceof Error ? error.message : "议题详情加载失败"
  } finally {
    loadingDetail.value = false
  }
}

async function selectSubject(subject: Subject) {
  selectedId.value = subject.subject_id
  activeTab.value = "feed"
  reviewError.value = ""
  reviewRefreshing.value = false
  reviewPending.value = false
  await nextTick()
  detailScroll.value?.scrollTo({ top: 0 })
  await loadSelectedData()
}

function applyReview(nextReview: SubjectReview) {
  review.value = nextReview
  reviewOpenSections.value = nextReview.sections.length ? ["0"] : []
  reviewOpenCites.value = []
  syncReviewPending(nextReview.version)
}

async function loadReviewOnly() {
  if (!selectedId.value) {
    return
  }
  applyReview(await subjectsApi.review(selectedId.value))
}

async function requestReviewUpdate() {
  if (!selectedId.value || reviewRefreshing.value || reviewPending.value) {
    return
  }
  const subjectId = selectedId.value
  const version = reviewVersion.value
  reviewError.value = ""
  reviewRefreshing.value = true
  try {
    const response = await subjectsApi.refreshReview(subjectId)
    if (response.pending !== false) {
      markReviewPending(subjectId, version)
      ElMessage.success(response.message || "已请求更新综述")
    }
  } catch {
    reviewError.value = "请求未送达，请重试"
  } finally {
    reviewRefreshing.value = false
  }
}

function reviewPendingKey(subjectId: string): string {
  return `${REVIEW_PENDING_KEY_PREFIX}${subjectId}`
}

function syncReviewPending(currentVersion: number) {
  if (!selectedId.value) {
    reviewPending.value = false
    return
  }
  reviewPending.value = readReviewPending(selectedId.value, currentVersion)
}

function readReviewPending(subjectId: string, currentVersion: number): boolean {
  const sessionVersion = sessionPendingReviews.value[subjectId]
  let pending = sessionVersion === currentVersion
  if (sessionVersion !== undefined && sessionVersion !== currentVersion) {
    delete sessionPendingReviews.value[subjectId]
  }

  try {
    const raw = window.localStorage.getItem(reviewPendingKey(subjectId))
    if (!raw) {
      return pending
    }
    const parsed = JSON.parse(raw) as { pending?: unknown; version?: unknown }
    const storedVersion = Number(parsed.version)
    if (parsed.pending === true && Number.isFinite(storedVersion) && storedVersion === currentVersion) {
      pending = true
    } else {
      window.localStorage.removeItem(reviewPendingKey(subjectId))
    }
  } catch {
    try {
      window.localStorage.removeItem(reviewPendingKey(subjectId))
    } catch {
      // Ignore storage cleanup failures.
    }
    return pending
  }

  return pending
}

function markReviewPending(subjectId: string, version: number) {
  sessionPendingReviews.value[subjectId] = version
  reviewPending.value = true
  try {
    window.localStorage.setItem(reviewPendingKey(subjectId), JSON.stringify({ pending: true, version }))
  } catch {
    // localStorage can be unavailable in private mode; session ref keeps the current page usable.
  }
}

function reviewUpdatedText(): string {
  if (!review.value?.updated_at) {
    return "尚未生成"
  }
  return `更新于 ${formatRelativeTime(review.value.updated_at, "尚无更新")}`
}

function resetForm() {
  form.name = ""
  form.nl_description = ""
  form.keywords = []
  form.status = "active"
  keywordInput.value = ""
  createError.value = ""
  formRef.value?.clearValidate()
}

function openCreate() {
  if (activeLimitReached.value) {
    return
  }
  drawerMode.value = "create"
  resetForm()
  drawerVisible.value = true
}

function openEdit(subject: Subject) {
  drawerMode.value = "edit"
  createError.value = ""
  form.name = subject.name
  form.nl_description = subject.nl_description
  form.keywords = [...subject.keywords]
  form.status = subject.status
  keywordInput.value = ""
  drawerVisible.value = true
}

function addKeyword() {
  const value = keywordInput.value.trim()
  if (!value || form.keywords.includes(value)) {
    keywordInput.value = ""
    return
  }
  form.keywords.push(value)
  keywordInput.value = ""
}

function removeKeyword(keyword: string) {
  form.keywords = form.keywords.filter((item) => item !== keyword)
}

async function submitSubject() {
  addKeyword()
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) {
    return
  }
  submitting.value = true
  createError.value = ""
  try {
    if (drawerMode.value === "create") {
      const created = await subjectsApi.create({
        name: form.name,
        nl_description: form.nl_description,
        keywords: form.keywords,
      })
      ElMessage.success("已创建，等待外部分类节拍命中")
      drawerVisible.value = false
      await loadSubjects(created.subject_id)
    } else if (selectedSubject.value) {
      const payload = {
        name: form.name,
        nl_description: form.nl_description,
        keywords: form.keywords,
        status: form.status,
      }
      const updated = await subjectsApi.update(selectedSubject.value.subject_id, payload)
      ElMessage.success("议题已更新")
      drawerVisible.value = false
      await loadSubjects(updated.subject_id)
    }
  } catch (error) {
    createError.value = error instanceof Error ? error.message : "保存失败，请重试"
  } finally {
    submitting.value = false
  }
}

async function toggleSubjectStatus(subject: Subject) {
  const nextStatus: SubjectStatus = subject.status === "active" ? "paused" : "active"
  try {
    const updated = await subjectsApi.update(subject.subject_id, { status: nextStatus })
    ElMessage.success(nextStatus === "paused" ? "议题已暂停" : "议题已恢复")
    await loadSubjects(updated.subject_id)
  } catch (error) {
    pageError.value = error instanceof Error ? error.message : "状态更新失败"
  }
}

async function confirmDelete(subject: Subject) {
  try {
    await ElMessageBox.confirm(
      "将删除议题及其命中关系。\n清除全部命中关系。\n删除后不可恢复。",
      `删除议题「${subject.name}」?`,
      {
        type: "warning",
        confirmButtonText: "删除",
        cancelButtonText: "取消",
        confirmButtonClass: "el-button--danger",
      },
    )
    await subjectsApi.delete(subject.subject_id)
    ElMessage.success("议题已删除")
    await loadSubjects()
  } catch (error) {
    if (error !== "cancel") {
      pageError.value = error instanceof Error ? error.message : "删除失败"
    }
  }
}

</script>

<template>
  <ApiKeyGuideEmpty v-if="needsApiKey" />
  <div v-else class="subjects-view">
    <el-result
      v-if="permissionError"
      icon="warning"
      title="无权限访问"
      sub-title="请使用管理员 API Key 后重试"
      class="permission-state"
    />

    <template v-else>
      <SubjectListPanel
        v-model:status-filter="statusFilter"
        :subjects="subjects"
        :filtered-subjects="filteredSubjects"
        :selected-id="selectedId"
        :active-count="activeCount"
        :active-limit-reached="activeLimitReached"
        :loading="loadingSubjects"
        :format-relative="(value) => formatRelativeTime(value ?? null, '尚无更新')"
        @create="openCreate"
        @select="selectSubject"
        @toggle="toggleSubjectStatus"
        @delete="confirmDelete"
      />

      <main ref="detailScroll" class="subjects-detail">
        <el-alert v-if="pageError" type="error" :closable="false" show-icon class="page-error">
          {{ pageError }}
        </el-alert>

        <el-empty
          v-if="!selectedSubject"
          description="选择一个议题查看持续更新"
          data-empty-state="first"
          class="detail-empty"
        >
          <el-button type="primary" :icon="Plus" :disabled="activeLimitReached" @click="openCreate">
            新建议题
          </el-button>
        </el-empty>

        <template v-else>
          <header class="detail-head">
            <div>
              <h2 data-detail-title :data-subject-id="selectedSubject.subject_id">
                议题：<span>{{ selectedSubject.name }}</span>
              </h2>
              <p>{{ selectedSubject.nl_description }}</p>
            </div>
            <el-button :icon="EditPen" @click="openEdit(selectedSubject)">编辑</el-button>
          </header>

          <el-tabs v-model="activeTab" class="subject-tabs">
            <el-tab-pane label="事件流" name="feed">
              <SubjectFeedTab
                :loading="loadingDetail"
                :items="feedItems"
                :hint-state="classifyHintState"
                :last-classified-at="lastClassifiedAt"
                :hint-title="classifyHintTitle"
                :hint-icon="classifyHintIcon"
                :hint-prefix="classifyHintPrefix"
                :hint-relative-text="classifyHintRelativeText"
                :hint-text="classifyHintText"
              />
            </el-tab-pane>

            <el-tab-pane label="摘要" name="digest">
              <SubjectDigestTab :loading="loadingDetail" :digests="digests" />
            </el-tab-pane>

            <el-tab-pane name="review">
              <template #label>
                <span data-review-tab-trigger>综述</span>
              </template>

              <SubjectReviewTab
                v-model:open-sections="reviewOpenSections"
                v-model:open-cites="reviewOpenCites"
                :loading="loadingDetail"
                :review="review"
                :version="reviewVersion"
                :sections="reviewSections"
                :has-trend="reviewHasTrend"
                :error="reviewError"
                :pending="reviewPending"
                :refreshing="reviewRefreshing"
                :request-button-text="reviewRequestButtonText"
                :updated-text="reviewUpdatedText()"
                @request="requestReviewUpdate"
              />

            </el-tab-pane>
          </el-tabs>
        </template>
      </main>
    </template>

    <SubjectFormDrawer
      v-model:visible="drawerVisible"
      v-model:form-ref="formRef"
      v-model:keyword-input="keywordInput"
      :title="drawerTitle"
      :form="form"
      :rules="rules"
      :error="createError"
      :submitting="submitting"
      @add-keyword="addKeyword"
      @remove-keyword="removeKeyword"
      @submit="submitSubject"
    />

  </div>
</template>

<style>
.subjects-view {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  height: calc(100vh - 50px);
  max-width: 1440px;
  margin: 0 auto;
  background: var(--bg-page);
}

.permission-state {
  grid-column: 1 / -1;
  align-self: center;
}

.subjects-master {
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg-card);
  border-right: 1px solid var(--border-light);
}

.master-head {
  padding: 16px 16px 12px;
  border-bottom: 1px solid var(--border-light);
}

.head-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.head-row h2 {
  flex: 1;
  margin: 0;
  font-size: var(--summary-font-size);
  font-weight: 600;
}

.count-badge,
.item-meta,
.feed-meta,
.digest-count {
  font-family: var(--font-mono);
  font-size: var(--xs-font-size);
  color: var(--text-tertiary);
}

.status-filter {
  width: 100%;
}

.status-filter :deep(.el-radio-button) {
  flex: 1;
}

.status-filter :deep(.el-radio-button__inner) {
  width: 100%;
}

.master-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 8px;
}

.limit-alert {
  margin-bottom: 8px;
}

.subject-skeleton {
  padding: 10px 12px;
}

.sk-name {
  width: 70%;
}

.sk-meta {
  width: 40%;
  margin-top: 6px;
}

.subject-item {
  position: relative;
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 10px 12px 10px 14px;
  margin-bottom: 2px;
  text-align: left;
  cursor: pointer;
  background: transparent;
  color: var(--text-primary);
  border: 0;
  border-left: 3px solid transparent;
  border-radius: var(--el-border-radius-base);
  font-family: var(--font-ui);
  transition: background var(--transition-base);
}

.subject-item:hover,
.subject-item.selected {
  background: var(--bg-inset);
}

.subject-item.selected {
  border-left-color: var(--color-primary);
}

.item-line {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.subject-name {
  flex: 1;
  min-width: 0;
  overflow-wrap: anywhere;
  font-size: var(--body-font-size);
  font-weight: 500;
}

.subject-item.selected .subject-name {
  color: var(--color-primary);
}

.paused-tag {
  flex-shrink: 0;
  padding: 0 6px;
  border: 1px solid var(--color-info);
  border-radius: var(--el-border-radius-small);
  color: var(--color-info);
  background: var(--bg-inset);
  font-size: var(--label-font-size);
  line-height: 16px;
}

.row-actions {
  position: absolute;
  right: 8px;
  top: 50%;
  display: flex;
  gap: 2px;
  opacity: 0;
  pointer-events: none;
  transform: translateY(-50%);
  background: var(--bg-inset);
  transition: opacity var(--transition-base);
}

.subject-item:hover .row-actions,
.subject-item:focus-within .row-actions {
  opacity: 1;
  pointer-events: auto;
}

.empty-state {
  padding: 40px 16px;
}

.subjects-detail {
  min-width: 0;
  overflow-y: auto;
  padding: 18px 24px 28px;
  background: var(--bg-page);
}

.page-error {
  margin-bottom: 12px;
}

.detail-empty {
  margin-top: 120px;
}

.detail-head {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  justify-content: space-between;
}

.detail-head h2 {
  margin: 0 0 8px;
  font-size: var(--summary-font-size);
  font-weight: 600;
}

.detail-head h2 span {
  color: var(--color-primary);
}

.detail-head p {
  margin: 0;
  color: var(--text-secondary);
  line-height: 1.8;
  overflow-wrap: anywhere;
}

.classify-hint {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding: 10px 14px;
  margin: 0 0 12px;
  border: 1px solid var(--border-light);
  border-radius: var(--el-border-radius-base);
  background: var(--bg-inset);
  color: var(--text-secondary);
  font-size: var(--small-font-size);
  line-height: 1.6;
  overflow-wrap: anywhere;
}

.classify-hint .el-icon {
  flex-shrink: 0;
  color: var(--color-info);
  font-size: var(--body-font-size);
}

.classify-hint.stale .el-icon {
  color: var(--color-warning);
}

.classify-hint.never {
  background: var(--color-warning-light);
}

.classify-hint.never .el-icon {
  color: var(--color-warning);
}

.classify-hint-skeleton {
  display: block;
}

.hint-skel-line {
  width: 260px;
  max-width: 100%;
}

.classify-hint-copy {
  min-width: 0;
}

.classify-hint-time {
  color: var(--text-primary);
  font-family: var(--font-mono);
  font-size: var(--xs-font-size);
  font-weight: 600;
}

.classify-hint.stale .classify-hint-time {
  color: var(--color-warning);
}

.subject-tabs {
  margin-top: 14px;
}

.tab-loading {
  display: grid;
  gap: 12px;
}

.feed-row,
.digest-card {
  padding: 14px 24px;
  margin-bottom: 12px;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--card-radius);
  box-shadow: var(--shadow-card);
  transition: box-shadow var(--transition-base), border-color var(--transition-base);
}

.feed-row:hover,
.digest-card:hover {
  border-color: var(--border-medium);
  box-shadow: var(--shadow-card-hover);
}

.feed-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 8px;
}

.tweet-text,
.digest-text {
  margin: 0;
  color: var(--text-secondary);
  font-family: var(--font-reading);
  font-size: var(--reading-font-size);
  line-height: var(--reading-line-height);
  letter-spacing: var(--reading-letter-spacing);
  overflow-wrap: anywhere;
}

.summary-box {
  margin-top: 10px;
  padding: 8px 12px;
  border-left: 3px solid var(--color-primary-light);
  border-radius: var(--el-border-radius-small);
  background: var(--bg-inset);
}

.summary-box span {
  font-size: var(--label-font-size);
  color: var(--color-primary);
}

.summary-box p {
  margin: 4px 0 0;
  color: var(--text-secondary);
  line-height: 1.8;
  overflow-wrap: anywhere;
}

.digest-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.interval-pill {
  padding: 2px 8px;
  border-radius: var(--el-border-radius-small);
  background: var(--bg-inset);
  color: var(--text-tertiary);
  font-family: var(--font-mono);
  font-size: var(--xs-font-size);
}

.highlight-collapse {
  margin-top: 10px;
  border-top: 1px solid var(--border-light);
  border-bottom: 0;
}

.highlight-item {
  padding: 8px 12px;
  border-left: 3px solid var(--color-primary-light);
  border-radius: var(--el-border-radius-small);
  background: var(--bg-inset);
}

.highlight-item p {
  margin: 0 0 6px;
  color: var(--text-secondary);
  line-height: 1.8;
}

.highlight-item code {
  color: var(--text-tertiary);
  font-family: var(--font-mono);
  font-size: var(--xs-font-size);
}

.review-pane {
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
  padding: 2px 9px;
  border-radius: var(--el-border-radius-base);
  color: var(--el-color-white);
  background: var(--color-primary);
  font-family: var(--font-mono);
  font-size: var(--small-font-size);
  font-weight: 600;
  line-height: 1.6;
  white-space: nowrap;
}

.review-version-badge.empty {
  background: var(--text-tertiary);
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
}

.review-skeleton {
  padding: 20px;
  margin-bottom: 20px;
  border: 1px solid var(--border-light);
  border-radius: var(--card-radius);
  background: var(--bg-card);
}

.review-skel-title {
  width: 40%;
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

.review-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  padding: 48px 20px;
  color: var(--color-danger);
  text-align: center;
}

.review-error .el-icon {
  font-size: 56px;
  opacity: 0.85;
}

.review-error p {
  margin: 0;
  color: var(--color-danger);
  font-family: var(--font-reading);
  font-size: var(--body-font-size);
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

.review-cite-item {
  padding: 10px 14px;
  border-left: 3px solid var(--color-primary-light);
  border-radius: 0 var(--el-border-radius-base) var(--el-border-radius-base) 0;
  background: var(--bg-inset);
  cursor: default;
}

.review-cite-item p {
  margin: 0 0 6px;
  color: var(--text-primary);
  font-family: var(--font-reading);
  font-size: var(--small-font-size);
  line-height: 1.8;
}

.review-cite-ids {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.review-cite-ids code {
  padding: 1px 7px;
  border: 1px solid var(--border-light);
  border-radius: var(--el-border-radius-small);
  background: var(--bg-card);
  color: var(--text-tertiary);
  font-family: var(--font-mono);
  font-size: var(--label-font-size);
  text-decoration: none;
  cursor: default;
}

.keyword-editor {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  width: 100%;
}

.keyword-input {
  width: 160px;
}

@media (min-width: 1800px) {
  .subjects-view {
    max-width: 1800px;
    grid-template-columns: 360px minmax(0, 1fr);
  }

  .subjects-detail {
    padding-left: 40px;
    padding-right: 40px;
  }
}
</style>
