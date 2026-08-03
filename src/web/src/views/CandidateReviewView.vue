<script setup lang="ts">
import { computed, h, nextTick, ref } from "vue"
import { useRouter } from "vue-router"
import { Refresh } from "@element-plus/icons-vue"
import { ElMessage } from "element-plus"
import ApiKeyGuideEmpty from "@/components/ApiKeyGuideEmpty.vue"
import LoadErrorState from "@/components/LoadErrorState.vue"
import { useApiKeyGuard } from "@/composables/useApiKeyGuard"
import { candidatesApi } from "@/api/candidates"
import { formatRelativeTime } from "@/utils/format"
import CandidateDossierCard from "@/views/candidates/CandidateDossierCard.vue"
import CandidateDecisionDialog from "@/views/candidates/CandidateDecisionDialog.vue"
import type {
  CandidateDetailResponse,
  CandidateDossier,
  CandidateStatusFilter,
  CandidateSummary,
} from "@/types"

type QueueLoadReason = "initial" | "filter" | "page" | "refresh"
type EmptyKind = "first" | "filter"

const router = useRouter()
const statusFilter = ref<CandidateStatusFilter>("pending")
const page = ref(1)
const pageSize = 20
const candidates = ref<CandidateSummary[]>([])
const total = ref(0)
const initialLoading = ref(false)
const refreshing = ref(false)
const queueError = ref("")
const queueLoaded = ref(false)
const updatedAt = ref<string | null>(null)
const emptyKind = ref<EmptyKind>("filter")
const queueListElement = ref<HTMLElement | null>(null)

const selectedCandidateId = ref<string | null>(null)
const detail = ref<CandidateDetailResponse | null>(null)
const detailLoading = ref(false)
const detailError = ref("")
const decidedIds = ref(new Set<string>())

const dialogVisible = ref(false)
const dialogDecision = ref<"approve" | "reject">("approve")
const dialogSubmitting = ref(false)
const dialogError = ref("")

const filters: Array<{ value: CandidateStatusFilter; label: string }> = [
  { value: "pending", label: "待审" },
  { value: "all", label: "全部" },
  { value: "discovered", label: "已发现" },
  { value: "assessed", label: "已预审" },
  { value: "approved", label: "已批准" },
  { value: "rejected", label: "已否决" },
]

const filterLabel = computed(() => (
  filters.find((item) => item.value === statusFilter.value)?.label ?? statusFilter.value
))
const selectedDossier = computed<CandidateDossier | null>(() => detail.value?.candidate ?? null)

function errorDetail(error: unknown): string {
  const typed = error as { response?: { status?: number; data?: { detail?: string } }; message?: string }
  return typed.response?.data?.detail || typed.message || "请求失败，请稍后重试"
}

function statusText(status: string): string {
  return {
    discovered: "已发现",
    assessed: "已预审",
    approved: "已批准",
    rejected: "已否决",
  }[status] ?? status
}

function statusClass(status: string): string {
  return ["discovered", "assessed", "approved", "rejected"].includes(status)
    ? `status-${status}`
    : "status-unknown"
}

function isInstitution(verifiedType: string | null): boolean {
  const value = verifiedType?.toLowerCase()
  return Boolean(value && !["blue", "individual"].includes(value))
}

async function detectEmptyKind(): Promise<EmptyKind> {
  if (statusFilter.value === "all") return "first"
  if (statusFilter.value !== "pending") return "filter"
  const allCandidates = await candidatesApi.list({ page: 1, page_size: 1 })
  return allCandidates.total === 0 ? "first" : "filter"
}

async function loadDetail(candidateId: string): Promise<void> {
  detailLoading.value = true
  detailError.value = ""
  try {
    detail.value = await candidatesApi.detail(candidateId)
  } catch (error) {
    detailError.value = errorDetail(error)
  } finally {
    detailLoading.value = false
  }
}

async function selectCandidate(candidateId: string): Promise<void> {
  selectedCandidateId.value = candidateId
  await loadDetail(candidateId)
}

async function loadQueue(reason: QueueLoadReason): Promise<void> {
  if (reason === "initial") initialLoading.value = true
  else refreshing.value = true
  queueError.value = ""
  try {
    const response = await candidatesApi.list({
      status: statusFilter.value === "all" ? undefined : statusFilter.value,
      page: page.value,
      page_size: pageSize,
    })
    candidates.value = response.candidates
    total.value = response.total
    updatedAt.value = new Date().toISOString()
    queueLoaded.value = true

    if (response.candidates.length === 0) {
      emptyKind.value = await detectEmptyKind()
      if (reason !== "page") {
        selectedCandidateId.value = null
        detail.value = null
        detailError.value = ""
      }
      return
    }

    const selectedStillVisible = response.candidates.some(
      (candidate) => candidate.candidate_id === selectedCandidateId.value,
    )
    const firstCandidate = response.candidates[0]
    if (!firstCandidate) return
    if (reason === "page") {
      if (!selectedCandidateId.value) {
        await selectCandidate(firstCandidate.candidate_id)
      } else if (selectedStillVisible && !detail.value) {
        await loadDetail(selectedCandidateId.value)
      }
      return
    }
    if (!selectedStillVisible) {
      await selectCandidate(firstCandidate.candidate_id)
    } else if (!detail.value && selectedCandidateId.value) {
      await loadDetail(selectedCandidateId.value)
    }
  } catch (error) {
    queueError.value = errorDetail(error)
  } finally {
    initialLoading.value = false
    refreshing.value = false
  }
}

async function loadInitial(): Promise<void> {
  await loadQueue("initial")
}

const { needsApiKey } = useApiKeyGuard(loadInitial)

async function changeFilter(filter: CandidateStatusFilter) {
  if (statusFilter.value === filter || refreshing.value) return
  statusFilter.value = filter
  page.value = 1
  await nextTick()
  queueListElement.value?.scrollTo({ top: 0 })
  await loadQueue("filter")
}

async function changePage(nextPage: number) {
  page.value = nextPage
  queueListElement.value?.scrollTo({ top: 0 })
  await loadQueue("page")
}

function openDecision(decision: "approve" | "reject") {
  dialogDecision.value = decision
  dialogError.value = ""
  dialogVisible.value = true
}

function showApprovedMessage() {
  ElMessage({
    type: "success",
    duration: 5000,
    message: h("span", { "data-testid": "crq-toast-approved" }, [
      "已批准并加入抓取名单　",
      h("a", {
        "data-testid": "crq-goto-follows-link",
        class: "message-link",
        onClick: () => void router.push("/follows"),
      }, "去关注管理 ↗"),
    ]),
  })
}

async function submitDecision(payload: {
  decision: "approve" | "reject"
  value: string | null
}) {
  if (!selectedCandidateId.value || dialogSubmitting.value) return
  dialogSubmitting.value = true
  dialogError.value = ""
  try {
    const request = payload.decision === "approve"
      ? { decision: payload.decision, brief_intro: payload.value }
      : { decision: payload.decision, reject_reason: payload.value }
    const response = await candidatesApi.review(selectedCandidateId.value, request)
    const row = candidates.value.find(
      (candidate) => candidate.candidate_id === selectedCandidateId.value,
    )
    if (row) row.status = response.status
    decidedIds.value = new Set(decidedIds.value).add(selectedCandidateId.value)
    await loadDetail(selectedCandidateId.value)
    dialogVisible.value = false
    if (payload.decision === "approve") showApprovedMessage()
    else {
      ElMessage({
        type: "success",
        message: h("span", { "data-testid": "crq-toast-rejected" }, "已否决留档"),
      })
    }
  } catch (error) {
    const status = (error as { response?: { status?: number } }).response?.status
    dialogError.value = errorDetail(error)
    if (status === 409) dialogError.value += "。刷新后可查看当前终态。"
  } finally {
    dialogSubmitting.value = false
  }
}

async function refreshAfterConflict() {
  dialogVisible.value = false
  await loadQueue("refresh")
}
</script>

<template>
  <div class="candidate-review">
    <div v-if="needsApiKey" class="permission-state" data-testid="crq-state-apikey">
      <ApiKeyGuideEmpty />
    </div>

    <div v-else-if="initialLoading && !queueLoaded" class="loading-layout" data-testid="crq-state-loading">
      <aside class="loading-queue">
        <el-skeleton :rows="9" animated />
      </aside>
      <main class="loading-detail">
        <el-skeleton :rows="14" animated />
      </main>
    </div>

    <div v-else-if="queueError && !queueLoaded" class="queue-fatal" data-testid="crq-state-error">
      <div data-testid="crq-error-retry">
        <LoadErrorState :retry="loadInitial" />
      </div>
    </div>

    <div
      v-else
      class="review-layout"
      :data-testid="candidates.length ? 'crq-state-success' : undefined"
    >
      <aside class="queue-column">
        <header class="queue-header">
          <div class="queue-title" data-testid="crq-queue-title">
            候选队列 · {{ filterLabel }}
            <span>（{{ total }}）</span>
          </div>
          <div class="filter-rows" data-testid="crq-status-filter">
            <div class="filter-row">
              <button
                v-for="filter in filters.slice(0, 2)"
                :key="filter.value"
                type="button"
                class="filter-button"
                :class="{ selected: statusFilter === filter.value }"
                :data-testid="`crq-filter-${filter.value}`"
                @click="changeFilter(filter.value)"
              >
                {{ filter.label }}
              </button>
            </div>
            <div class="filter-row">
              <button
                v-for="filter in filters.slice(2)"
                :key="filter.value"
                type="button"
                class="filter-button"
                :class="{ selected: statusFilter === filter.value }"
                :data-testid="`crq-filter-${filter.value}`"
                @click="changeFilter(filter.value)"
              >
                {{ filter.label }}
              </button>
            </div>
          </div>
          <div class="refresh-row">
            <el-button
              size="small"
              :icon="Refresh"
              :loading="refreshing"
              data-testid="crq-refresh-btn"
              @click="loadQueue('refresh')"
            >
              刷新
            </el-button>
            <span data-testid="crq-data-timestamp">
              {{ updatedAt ? `更新于 ${formatRelativeTime(updatedAt)}` : "尚未更新" }}
            </span>
          </div>
        </header>

        <div
          ref="queueListElement"
          v-loading="refreshing"
          class="queue-list"
          data-testid="crq-queue-list"
        >
          <button
            v-for="candidate in candidates"
            :key="candidate.candidate_id"
            type="button"
            class="queue-row"
            :class="{
              selected: selectedCandidateId === candidate.candidate_id,
              decided: decidedIds.has(candidate.candidate_id),
            }"
            :data-testid="decidedIds.has(candidate.candidate_id)
              ? 'crq-queue-row-decided'
              : 'crq-queue-row'"
            :data-candidate-id="candidate.candidate_id"
            @click="selectCandidate(candidate.candidate_id)"
          >
            <span class="row-primary">
              <span class="status-badge" :class="statusClass(candidate.status)">
                <span class="status-dot" />{{ statusText(candidate.status) }}
              </span>
              <span
                class="row-name"
                :title="`@${candidate.username}${candidate.display_name ? `（${candidate.display_name}）` : ''}`"
              >
                @{{ candidate.username }}
                <small v-if="candidate.display_name">{{ candidate.display_name }}</small>
              </span>
            </span>
            <span class="row-secondary">
              <span v-if="isInstitution(candidate.verified_type)" class="warning-tag">机构认证</span>
              <span v-if="candidate.is_automated" class="warning-tag">自动化账号</span>
              <span>引用 {{ candidate.citation_total }} 次 · {{ candidate.source_diversity }} 个信源</span>
              <span>{{ formatRelativeTime(candidate.first_discovered_at) }}发现</span>
            </span>
          </button>

          <div
            v-if="!candidates.length && queueLoaded"
            class="queue-empty"
            :data-testid="emptyKind === 'first'
              ? 'crq-state-empty-first'
              : 'crq-state-empty-filter'"
          >
            <el-empty
              :description="emptyKind === 'first'
                ? '还没有候选信源。候选由 Agent 从存量语料挖掘产生，等 Agent 跑过挖掘后再来看看。'
                : `没有「${filterLabel}」状态的候选`"
            >
              <el-button
                v-if="emptyKind === 'filter' && statusFilter !== 'pending'"
                data-testid="crq-empty-back-pending"
                @click="changeFilter('pending')"
              >
                切回待审
              </el-button>
            </el-empty>
          </div>
        </div>

        <footer v-if="total > pageSize" class="queue-pagination" data-testid="crq-queue-pagination">
          <span>共 {{ total }} 条</span>
          <el-pagination
            small
            layout="prev, pager, next"
            :current-page="page"
            :page-size="pageSize"
            :total="total"
            @current-change="changePage"
          />
        </footer>
      </aside>

      <main class="detail-column">
        <div v-if="detailLoading" class="detail-loading">
          <el-skeleton :rows="14" animated />
        </div>
        <div v-else-if="detailError" class="detail-error">
          <LoadErrorState
            :retry="() => selectedCandidateId ? loadDetail(selectedCandidateId) : undefined"
          />
        </div>
        <CandidateDossierCard
          v-else-if="detail"
          :detail="detail"
          @approve="openDecision('approve')"
          @reject="openDecision('reject')"
        />
        <el-empty v-else description="从左侧选择一个候选信源查看完整档案" />
      </main>
    </div>

    <CandidateDecisionDialog
      v-model="dialogVisible"
      :decision="dialogDecision"
      :candidate="selectedDossier"
      :submitting="dialogSubmitting"
      :error="dialogError"
      @confirm="submitDecision"
      @refresh="refreshAfterConflict"
    />
  </div>
</template>

<style scoped>
.candidate-review {
  height: calc(100vh - 50px);
  margin: -20px;
  overflow: hidden;
  background: var(--bg-page);
}

.permission-state,
.queue-fatal {
  display: flex;
  height: 100%;
  align-items: center;
  justify-content: center;
}

.loading-layout,
.review-layout {
  display: flex;
  height: 100%;
  min-height: 0;
}

.loading-queue,
.queue-column {
  width: 320px;
  flex: none;
  border-right: 1px solid var(--border-light);
  background: var(--bg-card);
}

.loading-queue,
.loading-detail,
.detail-loading {
  padding: 20px;
}

.loading-detail,
.detail-column {
  min-width: 0;
  flex: 1;
}

.queue-column {
  display: flex;
  min-height: 0;
  flex-direction: column;
}

.queue-header {
  display: flex;
  flex: none;
  flex-direction: column;
  gap: 10px;
  padding: 16px 16px 12px;
  border-bottom: 1px solid var(--border-light);
}

.queue-title {
  display: flex;
  align-items: baseline;
  gap: 6px;
  color: var(--text-primary);
  font-size: var(--body-font-size);
}

.queue-title span { color: var(--text-secondary); font-family: var(--font-mono); font-size: var(--small-font-size); }
.filter-rows { display: flex; flex-direction: column; gap: 6px; }
.filter-row { display: flex; flex-wrap: nowrap; gap: 6px; }

.filter-button {
  padding: 4px 10px;
  border: 1px solid var(--border-light);
  border-radius: var(--el-border-radius-base);
  background: var(--bg-card);
  color: var(--text-secondary);
  cursor: pointer;
  font-family: inherit;
  font-size: var(--xs-font-size);
  transition: all 200ms cubic-bezier(0.4, 0, 0.2, 1);
}
.filter-button:hover { border-color: var(--color-primary); color: var(--color-primary); }
.filter-button:active { background: var(--color-primary-lighter); }
.filter-button.selected { border-color: var(--color-primary); background: var(--color-primary); color: var(--el-color-white); }

.refresh-row { display: flex; align-items: center; gap: 8px; }
.refresh-row > span { color: var(--text-tertiary); font-family: var(--font-mono); font-size: var(--xs-font-size); }

.queue-list { min-height: 0; flex: 1; overflow-y: auto; }
.queue-row {
  display: flex;
  width: 100%;
  flex-direction: column;
  gap: 5px;
  padding: 12px 16px;
  border: 0;
  border-bottom: 1px solid var(--border-light);
  background: var(--bg-card);
  color: var(--text-primary);
  cursor: pointer;
  font-family: inherit;
  text-align: left;
  transition: background 200ms cubic-bezier(0.4, 0, 0.2, 1), opacity 200ms cubic-bezier(0.4, 0, 0.2, 1);
}
.queue-row:hover { background: var(--bg-inset); }
.queue-row.selected { background: var(--color-primary-lighter); box-shadow: inset 3px 0 0 var(--color-primary); }
.queue-row.decided { opacity: 0.55; }
.queue-row.decided:hover { opacity: 0.75; }
.row-primary,
.row-secondary { display: flex; align-items: center; gap: 8px; }
.row-secondary { flex-wrap: wrap; color: var(--text-tertiary); font-size: var(--xs-font-size); }
.row-name { min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: var(--small-font-size); }
.row-name small { color: var(--text-secondary); font-size: var(--xs-font-size); font-weight: 400; }

.status-badge,
.warning-tag {
  display: inline-flex;
  flex: none;
  align-items: center;
  gap: 4px;
  padding: 1px 7px;
  border-radius: var(--el-border-radius-base);
  font-size: var(--label-font-size);
}
.status-dot { width: 6px; height: 6px; border-radius: 50%; background: currentcolor; }
.status-discovered { color: var(--color-info); background: var(--bg-inset); }
.status-assessed { color: var(--color-primary); background: var(--color-primary-lighter); }
.status-approved { color: var(--color-success); background: var(--color-success-light); }
.status-rejected { color: var(--color-danger); background: var(--color-danger-light); }
.status-unknown { color: var(--text-secondary); background: var(--bg-inset); }
.warning-tag { color: var(--color-warning); background: var(--color-warning-light); }

.queue-empty { display: flex; min-height: 320px; align-items: center; justify-content: center; padding: 16px; }
.queue-empty :deep(.el-empty__description p) { color: var(--text-secondary); font-size: var(--small-font-size); line-height: 1.8; }
.queue-pagination { display: flex; flex: none; align-items: center; justify-content: space-between; padding: 10px 16px; border-top: 1px solid var(--border-light); color: var(--text-tertiary); font-size: var(--xs-font-size); }

.detail-column {
  overflow-y: auto;
  padding: var(--card-gap);
}

.detail-error,
.detail-loading { max-width: 980px; border: 1px solid var(--border-light); border-radius: var(--card-radius); background: var(--bg-card); }

:global(.message-link) { color: var(--color-primary); cursor: pointer; }

@media (min-width: 1800px) {
  .loading-queue,
  .queue-column { width: 360px; }
}
</style>
