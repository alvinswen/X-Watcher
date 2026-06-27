<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from "vue"
import type { FormInstance, FormRules } from "element-plus"
import { ElMessage, ElMessageBox } from "element-plus"
import {
  ChatLineSquare,
  Clock,
  Delete,
  EditPen,
  Loading,
  Lock,
  Plus,
  VideoPause,
  VideoPlay,
} from "@element-plus/icons-vue"
import { subjectsApi } from "@/api/subjects"
import type {
  Subject,
  SubjectDigest,
  SubjectFeedItem,
  SubjectStatus,
} from "@/types"

interface SubjectForm {
  name: string
  nl_description: string
  keywords: string[]
  status: SubjectStatus
}

const subjects = ref<Subject[]>([])
const selectedId = ref<string | null>(null)
const feedItems = ref<SubjectFeedItem[]>([])
const digests = ref<SubjectDigest[]>([])
const activeTab = ref<"feed" | "digest">("feed")
const statusFilter = ref<"all" | SubjectStatus>("all")
const loadingSubjects = ref(false)
const loadingDetail = ref(false)
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
const nlDescriptionLocked = computed(() => drawerMode.value === "edit" && isBackfilling(selectedSubject.value))

onMounted(() => {
  void loadSubjects()
})

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
    permissionError.value = message.includes("认证") || message.includes("403") || message.includes("API Key")
    pageError.value = permissionError.value ? "" : message
  } finally {
    loadingSubjects.value = false
  }
}

async function loadSelectedData() {
  if (!selectedId.value) {
    feedItems.value = []
    digests.value = []
    return
  }
  loadingDetail.value = true
  try {
    const [feed, digestResponse] = await Promise.all([
      subjectsApi.feed(selectedId.value),
      subjectsApi.digests(selectedId.value),
    ])
    feedItems.value = feed.items
    digests.value = digestResponse.items
  } catch (error) {
    pageError.value = error instanceof Error ? error.message : "议题详情加载失败"
  } finally {
    loadingDetail.value = false
  }
}

async function selectSubject(subject: Subject) {
  selectedId.value = subject.subject_id
  activeTab.value = "feed"
  await nextTick()
  detailScroll.value?.scrollTo({ top: 0 })
  await loadSelectedData()
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
      ElMessage.success("已创建，正在后台回填")
      drawerVisible.value = false
      await loadSubjects(created.subject_id)
    } else if (selectedSubject.value) {
      const payload = nlDescriptionLocked.value
        ? { name: form.name, keywords: form.keywords, status: form.status }
        : { name: form.name, nl_description: form.nl_description, keywords: form.keywords, status: form.status }
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
      "将取消进行中回填并删除议题及其命中关系。\n清除全部命中关系。\n删除后不可恢复。",
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

function isBackfilling(subject: Subject | null): boolean {
  const status = subject?.backfill_task?.status
  return status === "pending" || status === "running"
}

function progressData(subject: Subject | null): string | undefined {
  if (!subject?.backfill_task?.progress) {
    return undefined
  }
  const progress = subject.backfill_task.progress
  return `${progress.current}/${progress.total}`
}

function progressText(subject: Subject | null): string {
  const progress = subject?.backfill_task?.progress
  if (!progress) {
    return "已处理 0/0 条"
  }
  return `已处理 ${progress.current}/${progress.total} 条`
}

function progressPercent(subject: Subject | null): number {
  return subject?.backfill_task?.progress?.percentage || 0
}

function formatRelative(value?: string | null): string {
  if (!value) {
    return "尚无更新"
  }
  const diff = Date.now() - new Date(value).getTime()
  if (diff < 60_000) {
    return "刚刚"
  }
  if (diff < 3_600_000) {
    return `${Math.floor(diff / 60_000)} 分钟前`
  }
  if (diff < 86_400_000) {
    return `${Math.floor(diff / 3_600_000)} 小时前`
  }
  return `${Math.floor(diff / 86_400_000)} 天前`
}

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value))
}

function formatHourLabel(hour: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})-(\d{2})$/.exec(hour)
  if (!match) {
    return `${hour}（UTC）`
  }
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  const hourPart = Number(match[4])
  const start = new Date(Date.UTC(year, month - 1, day, hourPart, 0, 0))
  const end = new Date(start.getTime() + 3_600_000)
  const datePart = new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
  }).format(start).replace(/\//g, "-")
  const startTime = new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(start)
  const endTime = new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(end)
  return `${datePart} ${startTime}-${endTime}（本地）`
}
</script>

<template>
  <div class="subjects-view">
    <el-result
      v-if="permissionError"
      icon="warning"
      title="无权限访问"
      sub-title="请使用管理员 API Key 后重试"
      class="permission-state"
    />

    <template v-else>
      <aside class="subjects-master">
        <div class="master-head">
          <div class="head-row">
            <h2>议题</h2>
            <span class="count-badge">活跃 {{ activeCount }}/20</span>
            <el-tooltip
              content="已达20活跃议题上限，请先停用旧议题"
              :disabled="!activeLimitReached"
              placement="bottom"
            >
              <span>
                <el-button
                  type="primary"
                  size="small"
                  :icon="Plus"
                  :disabled="activeLimitReached"
                  @click="openCreate"
                >
                  新建
                </el-button>
              </span>
            </el-tooltip>
          </div>

          <el-radio-group v-model="statusFilter" size="small" class="status-filter">
            <el-radio-button label="all">全部</el-radio-button>
            <el-radio-button label="active">活跃</el-radio-button>
            <el-radio-button label="paused">暂停</el-radio-button>
          </el-radio-group>
        </div>

        <div class="master-list">
          <el-alert
            v-if="activeLimitReached"
            type="warning"
            :closable="false"
            show-icon
            class="limit-alert"
          >
            已达议题上限，先停用旧议题
          </el-alert>

          <template v-if="loadingSubjects">
            <el-skeleton v-for="idx in 6" :key="idx" animated class="subject-skeleton">
              <template #template>
                <el-skeleton-item variant="text" class="sk-name" />
                <el-skeleton-item variant="text" class="sk-meta" />
              </template>
            </el-skeleton>
          </template>

          <el-empty
            v-else-if="subjects.length === 0"
            description="还没有议题，去创建"
            data-empty-state="first"
            class="empty-state"
          >
            <el-button type="primary" :icon="Plus" @click="openCreate">新建议题</el-button>
          </el-empty>

          <el-empty
            v-else-if="filteredSubjects.length === 0"
            description="当前过滤无结果，调整过滤"
            data-empty-state="filtered"
            class="empty-state"
          />

          <template v-else>
            <button
              v-for="subject in filteredSubjects"
              :key="subject.subject_id"
              class="subject-item"
              :class="{ selected: subject.subject_id === selectedId }"
              :data-subject-id="subject.subject_id"
              :data-status="subject.status"
              :data-selected="subject.subject_id === selectedId ? 'true' : undefined"
              @click="selectSubject(subject)"
            >
              <span class="item-line">
                <span class="subject-name" :title="subject.name">{{ subject.name }}</span>
                <span v-if="subject.status === 'paused'" data-paused-tag class="paused-tag">暂停</span>
              </span>
              <span class="item-meta">{{ formatRelative(subject.last_updated_at || subject.updated_at) }}</span>
              <span class="row-actions">
                <el-button
                  text
                  size="small"
                  :icon="subject.status === 'active' ? VideoPause : VideoPlay"
                  @click.stop="toggleSubjectStatus(subject)"
                >
                  {{ subject.status === "active" ? "暂停" : "恢复" }}
                </el-button>
                <el-button
                  text
                  size="small"
                  type="danger"
                  :icon="Delete"
                  @click.stop="confirmDelete(subject)"
                >
                  删除
                </el-button>
              </span>
            </button>
          </template>
        </div>
      </aside>

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

          <section
            v-if="isBackfilling(selectedSubject)"
            class="backfill-box"
            :data-backfill-progress="progressData(selectedSubject)"
          >
            <div class="backfill-line">
              <el-icon><Loading /></el-icon>
              <span>回填进行中</span>
              <span class="progress-count">{{ progressText(selectedSubject) }}</span>
            </div>
            <el-progress
              :percentage="progressPercent(selectedSubject)"
              :show-text="false"
              :stroke-width="6"
              color="var(--color-primary)"
            />
          </section>

          <el-tabs v-model="activeTab" class="subject-tabs">
            <el-tab-pane label="feed" name="feed">
              <div v-if="loadingDetail" class="tab-loading">
                <el-skeleton v-for="idx in 3" :key="idx" animated />
              </div>

              <el-empty
                v-else-if="feedItems.length === 0"
                description="暂无相关推文，等待下次抓取"
                data-empty-state="no-tweets"
                class="empty-state"
              >
                <el-icon><ChatLineSquare /></el-icon>
              </el-empty>

              <article
                v-for="item in feedItems"
                v-else
                :key="item.tweet_id"
                class="feed-row"
              >
                <div class="feed-meta">
                  <span>@{{ item.author_username || item.author }}</span>
                  <span>{{ formatDateTime(item.created_at) }}</span>
                  <span>{{ item.tweet_id }}</span>
                </div>
                <p class="tweet-text">{{ item.text }}</p>
                <div v-if="item.summary" class="summary-box">
                  <span>AI 摘要</span>
                  <p>{{ item.summary }}</p>
                </div>
              </article>
            </el-tab-pane>

            <el-tab-pane label="digest" name="digest">
              <div v-if="loadingDetail" class="tab-loading">
                <el-skeleton v-for="idx in 2" :key="idx" animated />
              </div>

              <el-empty
                v-else-if="digests.length === 0"
                description="暂无滚动新闻，等待下次抓取"
                data-empty-state="no-tweets"
                class="empty-state"
              >
                <el-icon><Clock /></el-icon>
              </el-empty>

              <article
                v-for="digest in digests"
                v-else
                :key="digest.hour"
                class="digest-card"
                :data-hour-bucket="digest.hour"
                :data-hour-label="formatHourLabel(digest.hour)"
              >
                <div class="digest-head">
                  <span class="hour-pill">{{ formatHourLabel(digest.hour) }}</span>
                  <span class="digest-count">{{ digest.tweet_count }} 条</span>
                </div>
                <p class="digest-text">{{ digest.digest_text }}</p>
                <el-collapse v-if="digest.highlights.length" class="highlight-collapse">
                  <el-collapse-item
                    v-for="(highlight, index) in digest.highlights"
                    :key="`${digest.hour}-${index}`"
                    :title="`引用 ${highlight.cited_tweet_ids.length} 条`"
                    :name="`${digest.hour}-${index}`"
                  >
                    <div
                      class="highlight-item"
                      :data-cited-tweet-ids="highlight.cited_tweet_ids.join(',')"
                    >
                      <p>{{ highlight.point }}</p>
                      <code>{{ highlight.cited_tweet_ids.join(", ") }}</code>
                    </div>
                  </el-collapse-item>
                </el-collapse>
              </article>
            </el-tab-pane>
          </el-tabs>
        </template>
      </main>
    </template>

    <el-drawer
      v-model="drawerVisible"
      :title="drawerTitle"
      direction="rtl"
      size="480px"
      class="subject-drawer"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <el-form-item label="议题名" prop="name">
          <el-input v-model="form.name" maxlength="120" show-word-limit />
        </el-form-item>
        <el-form-item label="语义描述" prop="nl_description">
          <el-input
            v-model="form.nl_description"
            type="textarea"
            :rows="6"
            :disabled="nlDescriptionLocked"
          />
          <p v-if="nlDescriptionLocked" class="locked-help">
            <el-icon><Lock /></el-icon>
            回填进行中不可改描述，如需修改请先停用或删重建
          </p>
        </el-form-item>
        <el-form-item label="关键词">
          <div class="keyword-editor">
            <el-tag
              v-for="keyword in form.keywords"
              :key="keyword"
              closable
              type="info"
              @close="removeKeyword(keyword)"
            >
              {{ keyword }}
            </el-tag>
            <el-input
              v-model="keywordInput"
              class="keyword-input"
              placeholder="输入后回车"
              @keydown.enter.prevent="addKeyword"
              @blur="addKeyword"
            />
          </div>
        </el-form-item>
        <el-form-item label="状态">
          <el-radio-group v-model="form.status">
            <el-radio-button label="active">活跃</el-radio-button>
            <el-radio-button label="paused">暂停</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-alert v-if="createError" type="error" :closable="false" show-icon>
          {{ createError }}
        </el-alert>
      </el-form>

      <template #footer>
        <el-button @click="drawerVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitSubject">
          保存
        </el-button>
      </template>
    </el-drawer>
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

.backfill-box {
  padding: 10px 14px;
  margin: 14px 0;
  border: 1px solid var(--color-info);
  border-radius: var(--el-border-radius-base);
  background: var(--bg-inset);
}

.backfill-line {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  color: var(--color-info);
  font-size: var(--small-font-size);
}

.progress-count {
  margin-left: auto;
  font-family: var(--font-mono);
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

.hour-pill {
  padding: 2px 8px;
  border-radius: var(--el-border-radius-small);
  background: var(--bg-inset);
  color: var(--color-info);
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

.keyword-editor {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  width: 100%;
}

.keyword-input {
  width: 160px;
}

.locked-help {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 6px 0 0;
  color: var(--color-warning);
  font-size: var(--small-font-size);
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
