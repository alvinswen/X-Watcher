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
import {
  markReviewPending,
  readReviewPending,
} from "@/views/subjects/reviewPending"
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
let selectedDataRequestSequence = 0

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
  const requestSequence = ++selectedDataRequestSequence
  const subjectId = selectedId.value
  if (!subjectId) {
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
      subjectsApi.feed(subjectId),
      subjectsApi.digests(subjectId),
    ])
    if (requestSequence !== selectedDataRequestSequence) {
      return
    }
    feedItems.value = feed.items
    lastClassifiedAt.value = feed.last_classified_at ?? null
    digests.value = digestResponse.items
    reviewError.value = ""
    try {
      await loadReviewOnly(subjectId, requestSequence)
    } catch {
      if (requestSequence === selectedDataRequestSequence) {
        reviewError.value = "综述加载失败"
      }
    }
  } catch (error) {
    if (requestSequence !== selectedDataRequestSequence) {
      return
    }
    pageError.value = error instanceof Error ? error.message : "议题详情加载失败"
  } finally {
    if (requestSequence === selectedDataRequestSequence) {
      loadingDetail.value = false
    }
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

async function loadReviewOnly(subjectId: string, requestSequence: number) {
  const nextReview = await subjectsApi.review(subjectId)
  if (requestSequence === selectedDataRequestSequence) {
    applyReview(nextReview)
  }
}

async function reloadReview(): Promise<void> {
  const subjectId = selectedId.value
  if (!subjectId) {
    return
  }
  const requestSequence = selectedDataRequestSequence
  reviewError.value = ""
  try {
    await loadReviewOnly(subjectId, requestSequence)
  } catch {
    if (requestSequence === selectedDataRequestSequence) {
      reviewError.value = "综述加载失败"
    }
  }
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
      reviewPending.value = markReviewPending(
        subjectId,
        version,
        sessionPendingReviews.value,
      )
      ElMessage.success(response.message || "已请求更新综述")
    }
  } catch {
    reviewError.value = "请求未送达，请重试"
  } finally {
    reviewRefreshing.value = false
  }
}

function syncReviewPending(currentVersion: number) {
  if (!selectedId.value) {
    reviewPending.value = false
    return
  }
  reviewPending.value = readReviewPending(
    selectedId.value,
    currentVersion,
    sessionPendingReviews.value,
  )
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
  <div v-else class="subjects-view" data-testid="subjects-view">
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

          <el-tabs
            v-model="activeTab"
            class="subject-tabs"
            data-testid="subjects-tabs"
          >
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
                :retry-review="reloadReview"
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
      @update:name="form.name = $event"
      @update:nl-description="form.nl_description = $event"
      @update:status="form.status = $event"
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

<style scoped>
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

.subject-tabs {
  margin-top: 14px;
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
