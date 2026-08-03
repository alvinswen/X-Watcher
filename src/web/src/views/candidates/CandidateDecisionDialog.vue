<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { Close, WarningFilled } from "@element-plus/icons-vue"
import type { CandidateDossier } from "@/types"

const props = defineProps<{
  modelValue: boolean
  decision: "approve" | "reject"
  candidate: CandidateDossier | null
  submitting: boolean
  error: string
}>()

const emit = defineEmits<{
  "update:modelValue": [visible: boolean]
  confirm: [payload: { decision: "approve" | "reject"; value: string | null }]
  refresh: []
}>()

const briefIntro = ref("")
const rejectReason = ref("")
const sourceReviewVersionStamp = /^\[xw-source-review@[^\]]+\]\s*/

const isApprove = computed(() => props.decision === "approve")
const statusText = computed(() => {
  const status = props.candidate?.status
  return {
    discovered: "已发现",
    assessed: "已预审",
    approved: "已批准",
    rejected: "已否决",
  }[status ?? ""] ?? status ?? "未知"
})
const chineseCount = computed(() => (briefIntro.value.match(/[一-鿿]/g) ?? []).length)
const briefIntroInvalid = computed(() => chineseCount.value > 10)
const hasAssessment = computed(() => Boolean(props.candidate?.assessment))
const isConflict = computed(() => props.error.includes("已是终态"))

watch(
  () => [props.modelValue, props.decision, props.candidate?.candidate_id] as const,
  ([visible]) => {
    if (!visible) return
    briefIntro.value = isApprove.value
      ? props.candidate?.assessment?.recommendation
        .replace(sourceReviewVersionStamp, "")
        .slice(0, 10) ?? ""
      : ""
    rejectReason.value = ""
  },
  { immediate: true },
)

function close() {
  if (!props.submitting) emit("update:modelValue", false)
}

function confirm() {
  if (props.submitting || briefIntroInvalid.value || !props.candidate) return
  const rawValue = isApprove.value ? briefIntro.value : rejectReason.value
  emit("confirm", {
    decision: props.decision,
    value: rawValue.trim() ? rawValue : null,
  })
}

function handleKeydown(event: KeyboardEvent) {
  if (!props.modelValue) return
  if (event.key === "Escape") {
    event.preventDefault()
    close()
    return
  }
  if (event.key !== "Enter") return
  const tagName = (event.target as HTMLElement | null)?.tagName.toLowerCase()
  if (tagName === "textarea") return
  if (tagName === "input") {
    event.preventDefault()
    return
  }
  event.preventDefault()
  confirm()
}

onMounted(() => document.addEventListener("keydown", handleKeydown))
onBeforeUnmount(() => document.removeEventListener("keydown", handleKeydown))
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    width="480px"
    :show-close="false"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    :teleported="false"
    :data-testid="isApprove ? 'crq-approve-dialog' : 'crq-reject-dialog'"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template #header>
      <div class="dialog-header">
        <span>
          {{ isApprove ? "批准" : "否决" }}候选信源 ·
          <span class="dialog-object">@{{ candidate?.username }}</span>
        </span>
        <el-button
          text
          :icon="Close"
          data-testid="crq-dialog-close"
          aria-label="关闭"
          :disabled="submitting"
          @click="close"
        />
      </div>
    </template>

    <div v-if="candidate" class="dialog-content">
      <div class="dialog-summary" data-testid="crq-dialog-summary">
        <span class="status-badge" :class="`status-${candidate.status}`">
          <span class="status-dot" />{{ statusText }}
        </span>
        <span>@{{ candidate.username }}</span>
        <span>
          引用 {{ candidate.mining.citation_total }} 次 ·
          {{ candidate.mining.source_diversity }} 个信源
        </span>
        <span>预审：{{ hasAssessment ? "已有结论" : "尚无" }}</span>
      </div>

      <div
        v-if="isApprove && !hasAssessment"
        class="direct-warning"
        data-testid="crq-direct-approve-warning"
      >
        <el-icon><WarningFilled /></el-icon>
        <span>
          该候选信息不全（尚无预审结论）。你仍可直接批准，或取消并等待 Agent
          补齐试读与预审。
        </span>
      </div>

      <div v-if="error" class="dialog-error" data-testid="crq-dialog-error">
        <span>{{ error }}</span>
        <el-button v-if="isConflict" link type="primary" @click="emit('refresh')">
          刷新队列
        </el-button>
      </div>

      <label v-if="isApprove" class="dialog-field">
        <span class="field-label">
          极简介绍
          <span>（选填 · {{ hasAssessment ? "预填预审意见头 10 字，可改可清空" : "无预审，不预填" }}）</span>
        </span>
        <el-input
          v-model="briefIntro"
          maxlength="50"
          :disabled="submitting"
          placeholder="选填，最多 10 个汉字"
          data-testid="crq-brief-intro-input"
          :class="{ 'is-field-error': briefIntroInvalid }"
        />
        <span v-if="briefIntroInvalid" class="field-error">最多 10 个汉字</span>
        <span v-else class="field-hint">
          最多 10 个汉字，将写入关注管理的「极简介绍」列
        </span>
      </label>

      <label v-else class="dialog-field">
        <span class="field-label">否决理由 <span>（选填）</span></span>
        <el-input
          v-model="rejectReason"
          type="textarea"
          :rows="3"
          maxlength="500"
          :disabled="submitting"
          placeholder="选填：记录否决原因，供后续复盘"
          data-testid="crq-reject-reason-input"
        />
      </label>

      <p class="decision-note">
        <template v-if="isApprove">
          批准后立即加入抓取名单并进入常规抓取周期；添加理由自动引用预审意见。如需撤销，去关注管理停用该账号。
        </template>
        <template v-else>
          否决后永久留档抑制，同一账号不再重复出现在挖掘结果。如需翻案，去关注管理手动添加。
        </template>
      </p>
    </div>

    <template #footer>
      <div class="dialog-footer">
        <span class="keyboard-hint">Esc 取消 · Enter 确认（输入框内除外）</span>
        <el-button
          data-testid="crq-dialog-cancel"
          :disabled="submitting"
          @click="close"
        >
          取消
        </el-button>
        <el-button
          :type="isApprove ? 'primary' : 'danger'"
          :plain="!isApprove"
          :loading="submitting"
          :disabled="briefIntroInvalid"
          data-testid="crq-dialog-confirm"
          @click="confirm"
        >
          {{ isApprove ? "确认批准" : "确认否决" }}
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.dialog-header,
.dialog-footer {
  display: flex;
  align-items: center;
}

.dialog-header {
  justify-content: space-between;
  color: var(--text-primary);
  font-size: var(--body-font-size);
}

.dialog-object,
.keyboard-hint {
  font-family: var(--font-mono);
}

.dialog-content {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.dialog-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: var(--el-border-radius-base);
  background: var(--bg-inset);
  color: var(--text-secondary);
  font-size: var(--small-font-size);
}

.status-badge {
  display: inline-flex;
  flex: none;
  align-items: center;
  gap: 4px;
  padding: 1px 7px;
  border-radius: var(--el-border-radius-base);
  font-size: var(--label-font-size);
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentcolor;
}

.status-discovered { color: var(--color-info); background: var(--bg-inset); }
.status-assessed { color: var(--color-primary); background: var(--color-primary-lighter); }
.status-approved { color: var(--color-success); background: var(--color-success-light); }
.status-rejected { color: var(--color-danger); background: var(--color-danger-light); }

.direct-warning,
.dialog-error {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 12px;
  border-radius: var(--el-border-radius-base);
  font-size: var(--small-font-size);
  line-height: 1.6;
}

.direct-warning {
  color: var(--color-warning);
  background: var(--color-warning-light);
}

.direct-warning .el-icon { flex: none; margin-top: 3px; }

.dialog-error {
  justify-content: space-between;
  color: var(--color-danger);
  background: var(--color-danger-light);
}

.dialog-field {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.field-label {
  color: var(--text-secondary);
  font-size: var(--xs-font-size);
}

.field-label span,
.field-hint,
.decision-note,
.keyboard-hint {
  color: var(--text-tertiary);
}

.field-hint,
.field-error,
.decision-note,
.keyboard-hint {
  font-size: var(--label-font-size);
}

.field-error { color: var(--color-danger); }

.is-field-error :deep(.el-input__wrapper) {
  box-shadow: 0 0 0 1px var(--color-danger) inset;
}

.decision-note {
  margin: 0;
  line-height: 1.6;
}

.dialog-footer {
  justify-content: flex-end;
  gap: 10px;
}

.keyboard-hint { margin-right: auto; }
</style>
