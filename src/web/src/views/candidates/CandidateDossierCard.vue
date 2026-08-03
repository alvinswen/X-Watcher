<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { useRouter } from "vue-router"
import TweetCard from "@/components/TweetCard.vue"
import { formatFullDateTime, formatNumber, formatRelativeTime } from "@/utils/format"
import { sampleTweetToCardData } from "@/types"
import type {
  CandidateDetailResponse,
  CandidateProfileSnapshot,
  TweetCardData,
} from "@/types"

const props = defineProps<{
  detail: CandidateDetailResponse
}>()

const emit = defineEmits<{
  approve: []
  reject: []
}>()

const router = useRouter()
const samplesExpanded = ref(false)

const candidate = computed(() => props.detail.candidate)
const profile = computed(() => candidate.value.profile_snapshot)
const isTerminal = computed(() => ["approved", "rejected"].includes(candidate.value.status))
const isInstitution = computed(() => {
  const value = profile.value?.verified_type?.toLowerCase()
  return Boolean(value && !["blue", "individual"].includes(value))
})
const sortedCiters = computed(() => (
  Object.entries(candidate.value.mining.citations)
    .sort(([, left], [, right]) => right.count - left.count)
))
const citationRows = computed(() => {
  const cardMap = new Map(
    props.detail.sample_citation_tweets.map((card) => [card.tweet_id, card]),
  )
  return candidate.value.mining.sample_citation_tweet_ids.map((tweetId) => ({
    tweetId,
    card: cardMap.get(tweetId) ?? null,
  }))
})
const sampleCards = computed(() => (
  candidate.value.sample?.tweets.map((tweet) => ({
    card: sampleTweetToCardData(tweet),
    evidence: candidate.value.assessment?.evidence_tweet_ids.includes(tweet.tweet_id) ?? false,
  })) ?? []
))
const visibleSamples = computed(() => (
  samplesExpanded.value ? sampleCards.value : sampleCards.value.slice(0, 5)
))

watch(
  () => candidate.value.candidate_id,
  () => { samplesExpanded.value = false },
)

function statusText(status: string): string {
  return {
    discovered: "已发现",
    assessed: "已预审",
    approved: "已批准",
    rejected: "已否决",
  }[status] ?? status
}

function statusClass(status: string): string {
  return (["discovered", "assessed", "approved", "rejected"] as string[])
    .includes(status)
    ? `status-${status}`
    : "status-unknown"
}

function verifiedTypeText(value: string | null): string {
  if (!value) return "未认证"
  const labels: Record<string, string> = {
    blue: "蓝 V（个人）",
    business: "机构认证",
    government: "政府认证",
  }
  return labels[value.toLowerCase()] ?? value
}

function profileValue(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "-"
  return typeof value === "number" ? formatNumber(value) : String(value)
}

function profileAvailable(snapshot: CandidateProfileSnapshot): string {
  if (!snapshot.unavailable) return "正常"
  return `不可用${snapshot.unavailable_reason ? `：${snapshot.unavailable_reason}` : ""}`
}

function accountCreatedText(value: string | null): string {
  if (!value) return "-"
  const createdAt = new Date(value)
  if (Number.isNaN(createdAt.getTime())) return value

  const month = String(createdAt.getUTCMonth() + 1).padStart(2, "0")
  const now = new Date()
  let years = now.getUTCFullYear() - createdAt.getUTCFullYear()
  if (
    now.getUTCMonth() < createdAt.getUTCMonth()
    || (
      now.getUTCMonth() === createdAt.getUTCMonth()
      && now.getUTCDate() < createdAt.getUTCDate()
    )
  ) years -= 1

  const age = years >= 0 ? `（${years} 年）` : ""
  return `${createdAt.getUTCFullYear()}-${month}${age}`
}

function openCitation(card: TweetCardData | null) {
  if (card) void router.push(`/tweets/${card.tweet_id}`)
}
</script>

<template>
  <article class="dossier-card">
    <header class="identity-bar" data-testid="crq-id-bar">
      <div class="identity-line">
        <span class="display-name">{{ profile?.display_name || candidate.username }}</span>
        <span class="handle">@{{ candidate.username }}</span>
        <span class="status-badge" :class="statusClass(candidate.status)">
          <span class="status-dot" />{{ statusText(candidate.status) }}
        </span>
        <span v-if="isInstitution" class="warning-tag">机构认证</span>
        <span v-if="profile?.is_automated" class="warning-tag">自动化账号</span>
      </div>
      <div class="identity-times">
        首次发现 {{ formatRelativeTime(candidate.mining.first_discovered_at) }} ·
        最近刷新 {{ formatRelativeTime(candidate.mining.last_mined_at) }}
      </div>
    </header>

    <section class="card-section" data-testid="crq-sec-profile">
      <h3 class="section-title">
        <span>①</span>账号档案
        <small v-if="candidate.profile_fetched_at">
          快照于 {{ formatRelativeTime(candidate.profile_fetched_at) }}
        </small>
      </h3>
      <div v-if="profile" class="profile-grid">
        <div class="profile-item"><span>认证类型</span><b>{{ verifiedTypeText(profile.verified_type) }}</b></div>
        <div class="profile-item"><span>是否自动化</span><b>{{ profile.is_automated ? "是" : "否" }}</b></div>
        <div class="profile-item"><span>粉丝数</span><b>{{ profileValue(profile.followers_count) }}</b></div>
        <div class="profile-item"><span>发文量</span><b>{{ profileValue(profile.statuses_count) }}</b></div>
        <div class="profile-item"><span>账号创建</span><b>{{ accountCreatedText(profile.account_created_at) }}</b></div>
        <div class="profile-item"><span>账号可用性</span><b>{{ profileAvailable(profile) }}</b></div>
        <div class="profile-item profile-span"><span>简介</span><b>{{ profileValue(profile.description) }}</b></div>
      </div>
      <p v-else class="section-empty">尚未拉取账号档案</p>
    </section>

    <section class="card-section" data-testid="crq-sec-signal">
      <h3 class="section-title"><span>②</span>挖掘信号</h3>
      <div class="signal-numbers">
        <div>
          <strong data-testid="crq-signal-citation-count">
            {{ candidate.mining.citation_total }}
          </strong>
          <span>引用总次数</span>
        </div>
        <div>
          <strong data-testid="crq-signal-source-count">
            {{ candidate.mining.source_diversity }}
          </strong>
          <span>来源多样性（个信源）</span>
        </div>
      </div>
      <div class="citer-list" data-testid="crq-citer-list">
        <span v-for="([username, signal]) in sortedCiters" :key="username" class="citer-chip">
          @{{ username }} <small>×{{ signal.count }}</small>
        </span>
      </div>
      <div v-if="citationRows.length" class="citation-list" data-testid="crq-citation-list">
        <button
          v-for="row in citationRows"
          :key="row.tweetId"
          type="button"
          class="citation-item"
          :class="{ missing: !row.card }"
          :disabled="!row.card"
          data-testid="crq-citation-item"
          :data-tweet-id="row.tweetId"
          @click="openCitation(row.card)"
        >
          <span class="citation-author">
            @{{ row.card?.author_username || "缺失" }}
          </span>
          <span class="citation-text" :title="row.card?.text || `推文 ${row.tweetId} 已不可用`">
            {{ row.card?.text || `推文 ${row.tweetId} 已不可用` }}
          </span>
          <span class="citation-time">
            {{ row.card ? formatRelativeTime(row.card.created_at) : "不可跳转" }}
          </span>
          <span v-if="row.card" class="citation-arrow">↗</span>
        </button>
      </div>
      <div v-if="candidate.mining.subject_tags.length" class="subject-tags">
        <span v-for="tag in candidate.mining.subject_tags" :key="tag">{{ tag }}</span>
      </div>
    </section>

    <section class="card-section" data-testid="crq-sec-assessment">
      <h3 class="section-title">
        <span>③</span>Agent 预审结论
        <small v-if="candidate.assessment">
          {{ formatRelativeTime(candidate.assessment.assessed_at) }} ·
          {{ candidate.assessment.assessed_by }}
        </small>
      </h3>
      <template v-if="candidate.assessment">
        <div class="score-rows">
          <div v-for="score in [
            ['原创观点占比', candidate.assessment.scores.originality],
            ['观点差异度', candidate.assessment.scores.difference],
            ['领域专业深度', candidate.assessment.scores.expertise],
          ]" :key="String(score[0])" class="score-row">
            <span>{{ score[0] }}</span>
            <span class="score-track">
              <span class="score-fill" :style="{ width: `${Number(score[1]) * 10}%` }" />
            </span>
            <b>{{ score[1] }}/10</b>
          </div>
        </div>
        <div class="assessment-text">{{ candidate.assessment.recommendation }}</div>
      </template>
      <p v-else class="section-empty">尚无预审结论</p>
    </section>

    <section class="card-section samples-section" data-testid="crq-sec-samples">
      <h3 class="section-title">
        <span>④</span>样本推文
        <small v-if="candidate.sample">
          试读拉样于 {{ formatRelativeTime(candidate.sample.fetched_at) }} ·
          共 {{ sampleCards.length }} 条 · 不入正式语料
        </small>
      </h3>
      <template v-if="candidate.sample && sampleCards.length">
        <div class="sample-grid">
          <div
            v-for="sample in visibleSamples"
            :key="sample.card.tweet_id"
            class="sample-card"
            :class="{ evidence: sample.evidence }"
            data-testid="crq-sample-card"
          >
            <span
              v-if="sample.evidence"
              class="evidence-badge"
              data-testid="crq-evidence-badge"
            >
              证据
            </span>
            <TweetCard :tweet="sample.card" :clickable="false" />
          </div>
        </div>
        <el-button
          v-if="sampleCards.length > 5"
          link
          class="sample-expand"
          data-testid="crq-sample-expand"
          @click="samplesExpanded = !samplesExpanded"
        >
          {{ samplesExpanded ? "收起" : `展开全部 ${sampleCards.length} 条` }}
        </el-button>
      </template>
      <p v-else class="section-empty">
        尚未试读拉样（由 Agent 执行），暂无样本推文
      </p>
    </section>

    <footer v-if="!isTerminal" class="action-bar">
      <el-button
        type="danger"
        plain
        data-testid="crq-reject-btn"
        @click="emit('reject')"
      >
        否决
      </el-button>
      <el-button type="primary" data-testid="crq-approve-btn" @click="emit('approve')">
        批准
      </el-button>
    </footer>
    <footer
      v-else-if="candidate.decision"
      class="decision-record"
      :data-testid="candidate.decision.verdict === 'reject'
        ? 'crq-decision-record-rejected'
        : 'crq-decision-record'"
    >
      <span class="status-badge" :class="statusClass(candidate.status)">
        <span class="status-dot" />{{ statusText(candidate.status) }}
      </span>
      <span>
        决策人 {{ candidate.decision.decided_by }} ·
        {{ formatFullDateTime(candidate.decision.decided_at) }}
      </span>
      <span v-if="candidate.decision.reject_reason">
        否决理由：{{ candidate.decision.reject_reason }}
      </span>
      <el-button
        v-if="candidate.decision.verdict === 'approve'"
        link
        type="primary"
        data-testid="crq-decision-record-link"
        @click="router.push('/follows')"
      >
        在关注管理中查看 ↗
      </el-button>
    </footer>
  </article>
</template>

<style scoped>
.dossier-card {
  max-width: 980px;
  overflow: visible;
  border: 1px solid var(--border-light);
  border-radius: var(--card-radius);
  background: var(--bg-card);
  box-shadow: var(--shadow-card);
}

.identity-bar {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: var(--card-padding);
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border-light);
}

.identity-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.display-name { color: var(--text-primary); font-size: var(--summary-font-size); }
.handle { color: var(--text-secondary); font-family: var(--font-mono); font-size: var(--small-font-size); }
.identity-times { color: var(--text-tertiary); font-size: var(--xs-font-size); }

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

.card-section {
  padding: var(--card-padding);
  padding-top: 18px;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--border-light);
}

.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 12px;
  color: var(--text-secondary);
  font-size: var(--small-font-size);
  font-weight: 400;
  letter-spacing: 0.04em;
}

.section-title > span { color: var(--text-tertiary); font-family: var(--font-mono); font-size: var(--label-font-size); }
.section-title small { margin-left: auto; color: var(--text-tertiary); font-size: var(--label-font-size); font-weight: 400; }

.profile-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px 24px; }
.profile-item { display: flex; gap: 8px; font-size: var(--small-font-size); }
.profile-item > span { flex: none; color: var(--text-tertiary); }
.profile-item > b { color: var(--text-primary); font-weight: 400; }
.profile-span { grid-column: 1 / -1; }

.section-empty { margin: 0; color: var(--text-tertiary); font-size: var(--small-font-size); }

.signal-numbers { display: flex; gap: 40px; margin-bottom: 14px; }
.signal-numbers > div { display: flex; flex-direction: column; gap: 2px; }
.signal-numbers strong { color: var(--text-primary); font-family: var(--font-mono); font-size: 28px; font-weight: 400; line-height: 1.2; }
.signal-numbers span { color: var(--text-tertiary); font-size: var(--xs-font-size); }

.citer-list { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 14px; }
.citer-chip,
.subject-tags span {
  padding: 2px 8px;
  border: 1px solid var(--border-light);
  border-radius: var(--el-border-radius-base);
  color: var(--text-secondary);
  background: var(--bg-inset);
  font-size: var(--xs-font-size);
}
.citer-chip small { color: var(--text-tertiary); font-family: var(--font-mono); }

.citation-list { overflow: hidden; border: 1px solid var(--border-light); border-radius: var(--el-border-radius-base); }
.citation-item {
  display: flex;
  width: 100%;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border: 0;
  background: var(--bg-card);
  color: var(--text-primary);
  cursor: pointer;
  font-family: inherit;
  font-size: var(--small-font-size);
  text-align: left;
  transition: background 200ms cubic-bezier(0.4, 0, 0.2, 1);
}
.citation-item + .citation-item { border-top: 1px solid var(--border-light); }
.citation-item:hover { background: var(--bg-inset); }
.citation-item.missing { color: var(--text-tertiary); cursor: not-allowed; }
.citation-author { flex: none; color: var(--text-secondary); font-family: var(--font-mono); font-size: var(--xs-font-size); }
.citation-text { min-width: 0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.citation-time { flex: none; color: var(--text-tertiary); font-size: var(--xs-font-size); }
.citation-arrow { flex: none; color: var(--color-primary); }
.subject-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
.subject-tags span { background: var(--bg-card); color: var(--text-tertiary); font-size: var(--label-font-size); }

.score-rows { display: flex; max-width: 520px; flex-direction: column; gap: 8px; margin-bottom: 14px; }
.score-row { display: flex; align-items: center; gap: 12px; font-size: var(--small-font-size); }
.score-row > span:first-child { width: 7.5em; flex: none; color: var(--text-secondary); }
.score-track { height: 6px; flex: 1; overflow: hidden; border-radius: 3px; background: var(--bg-inset); }
.score-fill { display: block; height: 100%; border-radius: 3px; background: var(--color-primary); }
.score-row b { width: 3.2em; flex: none; color: var(--text-primary); font-family: var(--font-mono); font-size: var(--xs-font-size); font-weight: 400; text-align: right; }

.assessment-text {
  padding: 12px 16px;
  border-radius: var(--el-border-radius-base);
  background: var(--bg-inset);
  color: var(--text-primary);
  font-family: var(--font-reading);
  font-size: var(--reading-font-size);
  letter-spacing: var(--reading-letter-spacing);
  line-height: var(--reading-line-height);
  white-space: pre-line;
}

.samples-section { border-bottom: 0; }
.sample-grid { display: grid; grid-template-columns: 1fr; gap: 12px; }
.sample-card { position: relative; min-width: 0; }
.sample-card.evidence :deep(.tweet-time-row) { padding-right: 58px; }
.evidence-badge {
  position: absolute;
  z-index: 1;
  top: 24px;
  right: 28px;
  padding: 0 7px;
  border: 1px solid var(--color-primary);
  border-radius: var(--el-border-radius-base);
  background: var(--color-primary-lighter);
  color: var(--color-primary);
  font-size: var(--label-font-size);
}
.sample-expand { margin-top: 8px; font-size: var(--small-font-size); }

.action-bar,
.decision-record {
  position: sticky;
  bottom: 0;
  z-index: 2;
  border-top: 1px solid var(--border-light);
  border-radius: 0 0 var(--card-radius) var(--card-radius);
  background: var(--bg-card);
}
.action-bar { display: flex; justify-content: flex-end; gap: 12px; padding: 16px 28px; }
.decision-record { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; padding: 12px 16px; color: var(--text-secondary); font-size: var(--small-font-size); line-height: 1.9; }

@media (min-width: 1800px) {
  .profile-grid { grid-template-columns: repeat(3, 1fr); }
  .sample-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>
