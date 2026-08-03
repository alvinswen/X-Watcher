import { defineComponent } from "vue"
import { flushPromises, mount } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import CandidateReviewView from "./CandidateReviewView.vue"
import CandidateDossierCard from "./candidates/CandidateDossierCard.vue"
import type {
  CandidateDetailResponse,
  CandidateDossier,
  CandidateListResponse,
  CandidateSampleTweet,
  CandidateSummary,
  TweetCardData,
} from "@/types"

const { list, detail, review, push, message } = vi.hoisted(() => ({
  list: vi.fn(),
  detail: vi.fn(),
  review: vi.fn(),
  push: vi.fn(),
  message: vi.fn(),
}))

vi.mock("@/api/candidates", () => ({
  candidatesApi: { list, detail, review },
}))

vi.mock("vue-router", () => ({
  useRouter: () => ({ push }),
}))

vi.mock("element-plus", () => ({ ElMessage: message }))

vi.mock("@/composables/useApiKeyGuard", async () => {
  const { ref } = await import("vue")
  return {
    useApiKeyGuard(load: () => Promise<void>) {
      void load()
      return { needsApiKey: ref(false) }
    },
  }
})

const fixedTime = "2026-08-02T12:00:00Z"

function summary(overrides: Partial<CandidateSummary> = {}): CandidateSummary {
  return {
    candidate_id: "candidatea",
    username: "candidatea",
    platform_user_id: "platform-42",
    status: "assessed",
    citation_total: 5,
    source_diversity: 2,
    subject_tags: ["量化交易"],
    first_discovered_at: fixedTime,
    last_mined_at: fixedTime,
    sample_fetched_at: fixedTime,
    assessed_at: fixedTime,
    decided_at: null,
    display_name: "候选甲",
    verified_type: "blue",
    is_automated: false,
    ...overrides,
  }
}

function sampleTweet(index: number): CandidateSampleTweet {
  return {
    tweet_id: `sample-${index}`,
    text: `样本推文 ${index}`,
    created_at: fixedTime,
    author_username: "candidatea",
    author_display_name: "候选甲",
    author_user_id: "platform-42",
    referenced_tweet_id: null,
    reference_type: null,
    media: null,
    referenced_tweet_text: null,
    referenced_tweet_media: null,
    referenced_tweet_author_username: null,
    article_preview: null,
  }
}

function dossier(overrides: Partial<CandidateDossier> = {}): CandidateDossier {
  return {
    candidate_id: "candidatea",
    username: "candidatea",
    platform_user_id: "platform-42",
    status: "assessed",
    mining: {
      citations: {
        source_a: { count: 3, citing_tweet_ids: ["tweet-1"] },
        source_b: { count: 2, citing_tweet_ids: ["tweet-2"] },
      },
      citation_total: 5,
      source_diversity: 2,
      sample_citation_tweet_ids: ["tweet-1", "tweet-missing"],
      subject_tags: ["量化交易"],
      first_discovered_at: fixedTime,
      last_mined_at: fixedTime,
    },
    profile_snapshot: {
      platform_user_id: "platform-42",
      username: "candidatea",
      display_name: "候选甲",
      is_blue_verified: false,
      verified_type: "business",
      profile_picture: null,
      cover_picture: null,
      description: "量化交易研究员",
      location: null,
      followers_count: 12847,
      following_count: 128,
      statuses_count: 3204,
      favourites_count: 100,
      media_count: 12,
      account_created_at: "2019-06-01T00:00:00Z",
      is_automated: true,
      possibly_sensitive: false,
      pinned_tweet_ids: null,
      unavailable: false,
      unavailable_reason: null,
      fetched_at: fixedTime,
    },
    profile_fetched_at: fixedTime,
    sample: {
      tweets: Array.from({ length: 6 }, (_, index) => sampleTweet(index + 1)),
      fetched_at: fixedTime,
    },
    assessment: {
      scores: { originality: 0, difference: 7, expertise: 10 },
      recommendation: "建议批准。\n完整保留英文 mixed content。",
      evidence_tweet_ids: ["sample-1"],
      assessed_at: fixedTime,
      assessed_by: "agent",
    },
    decision: null,
    ...overrides,
  }
}

function card(): TweetCardData {
  return {
    tweet_id: "tweet-1",
    text: "样例推文正文",
    created_at: fixedTime,
    author_username: "source_a",
    author_display_name: "Source A",
    summary_text: null,
    translation_text: null,
    media: null,
    reference_type: null,
    referenced_tweet_id: null,
    referenced_tweet_text: null,
    referenced_tweet_author_username: null,
    referenced_tweet_media: null,
  }
}

function detailResponse(candidate = dossier()): CandidateDetailResponse {
  return {
    candidate,
    sample_citation_tweets: [card()],
    missing_citation_tweet_ids: ["tweet-missing"],
  }
}

function listResponse(items = [summary()]): CandidateListResponse {
  return {
    candidates: items,
    count: items.length,
    total: items.length,
    page: 1,
    page_size: 20,
  }
}

const ElButtonStub = defineComponent({
  name: "ElButton",
  props: { disabled: Boolean, loading: Boolean },
  emits: ["click"],
  template: `<button :disabled="disabled || loading" @click="$emit('click')"><slot /></button>`,
})

const DossierStub = defineComponent({
  name: "CandidateDossierCard",
  props: { detail: { type: Object, required: true } },
  emits: ["approve", "reject"],
  template: `
    <div data-testid="dossier-stub">
      <span>{{ detail.candidate.candidate_id }}</span>
      <button data-testid="crq-approve-btn" @click="$emit('approve')">批准</button>
      <button data-testid="crq-reject-btn" @click="$emit('reject')">否决</button>
    </div>
  `,
})

const DialogStub = defineComponent({
  name: "CandidateDecisionDialog",
  props: {
    modelValue: Boolean,
    decision: { type: String, required: true },
  },
  emits: ["update:modelValue", "confirm", "refresh"],
  template: `
    <div v-if="modelValue" data-testid="decision-dialog-stub">
      <button
        data-testid="dialog-submit"
        @click="$emit('confirm', { decision, value: '量化研究' })"
      >提交</button>
    </div>
  `,
})

function mountView() {
  return mount(CandidateReviewView, {
    global: {
      directives: { loading: () => {} },
      stubs: {
        CandidateDossierCard: DossierStub,
        CandidateDecisionDialog: DialogStub,
        ApiKeyGuideEmpty: { template: "<div>配置 API Key</div>" },
        LoadErrorState: { template: "<div>加载失败</div>" },
        ElButton: ElButtonStub,
        ElSkeleton: { template: "<div>骨架</div>" },
        ElEmpty: { props: ["description"], template: "<div><span>{{ description }}</span><slot /></div>" },
        ElPagination: { template: "<div />" },
      },
    },
  })
}

describe("CandidateReviewView", () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-08-03T12:00:00Z"))
    list.mockReset()
    detail.mockReset()
    review.mockReset()
    push.mockReset()
    message.mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it("loads the pending queue and selects the first dossier", async () => {
    list.mockResolvedValue(listResponse())
    detail.mockResolvedValue(detailResponse())

    const wrapper = mountView()
    await flushPromises()

    expect(list).toHaveBeenCalledWith({ status: "pending", page: 1, page_size: 20 })
    expect(wrapper.get("[data-testid='crq-queue-title']").text()).toContain("候选队列 · 待审")
    expect(wrapper.findAll("[data-testid='crq-queue-row']")).toHaveLength(1)
    expect(wrapper.get("[data-testid='dossier-stub']").text()).toContain("candidatea")
  })

  it("links all four filter feedbacks and renders a named filter empty state", async () => {
    list
      .mockResolvedValueOnce(listResponse())
      .mockResolvedValueOnce(listResponse([]))
    detail.mockResolvedValue(detailResponse())
    const wrapper = mountView()
    await flushPromises()

    await wrapper.get("[data-testid='crq-filter-rejected']").trigger("click")
    await flushPromises()

    expect(list).toHaveBeenLastCalledWith({ status: "rejected", page: 1, page_size: 20 })
    expect(wrapper.get("[data-testid='crq-queue-title']").text()).toContain("已否决")
    expect(wrapper.get("[data-testid='crq-state-empty-filter']").text())
      .toContain("没有「已否决」状态的候选")
    expect(wrapper.get("[data-testid='crq-filter-rejected']").classes()).toContain("selected")
  })

  it("keeps a reviewed row clickable and fades it without reloading the queue", async () => {
    list.mockResolvedValue(listResponse())
    detail
      .mockResolvedValueOnce(detailResponse())
      .mockResolvedValueOnce(detailResponse(dossier({
        status: "approved",
        decision: {
          verdict: "approve",
          decided_by: "admin",
          decided_at: fixedTime,
          reject_reason: null,
          follow_id: 42,
          follow_username: "candidatea",
        },
      })))
    review.mockResolvedValue({
      candidate_id: "candidatea",
      status: "approved",
      follow_id: 42,
      follow_username: "candidatea",
      platform_user_id: "platform-42",
      notice: null,
    })
    const wrapper = mountView()
    await flushPromises()

    await wrapper.get("[data-testid='crq-approve-btn']").trigger("click")
    await wrapper.get("[data-testid='dialog-submit']").trigger("click")
    await flushPromises()

    expect(review).toHaveBeenCalledOnce()
    expect(list).toHaveBeenCalledOnce()
    expect(wrapper.get("[data-testid='crq-queue-row-decided']").classes()).toContain("decided")
    expect(wrapper.get("[data-testid='crq-queue-row-decided']").attributes("disabled"))
      .toBeUndefined()
    expect(message).toHaveBeenCalledOnce()
  })
})

const TweetCardStub = defineComponent({
  name: "TweetCard",
  props: { tweet: { type: Object, required: true } },
  template: `<div class="tweet-card-stub">{{ tweet.tweet_id }} · {{ tweet.text }}</div>`,
})

function mountDossier(candidate = dossier()) {
  return mount(CandidateDossierCard, {
    props: { detail: detailResponse(candidate) },
    global: {
      stubs: {
        TweetCard: TweetCardStub,
        ElButton: ElButtonStub,
      },
    },
  })
}

describe("CandidateDossierCard", () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-08-03T12:00:00Z"))
    push.mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it("keeps citation examples and candidate samples in distinct interactive forms", async () => {
    const wrapper = mountDossier()

    expect(wrapper.findAll("[data-testid='crq-citation-item']")).toHaveLength(2)
    expect(wrapper.findAll("[data-testid='crq-sample-card']")).toHaveLength(5)
    expect(wrapper.findAll("[data-testid='crq-evidence-badge']")).toHaveLength(1)
    expect(wrapper.text()).toContain("0/10")
    expect(wrapper.text()).toContain("10/10")

    await wrapper.findAll("[data-testid='crq-citation-item']")[0]?.trigger("click")
    expect(push).toHaveBeenCalledWith("/tweets/tweet-1")
    expect(wrapper.findAll("[data-testid='crq-citation-item']")[1]?.attributes("disabled"))
      .toBeDefined()

    await wrapper.get("[data-testid='crq-sample-expand']").trigger("click")
    expect(wrapper.findAll("[data-testid='crq-sample-card']")).toHaveLength(6)
    expect(wrapper.get("[data-testid='crq-sample-expand']").text()).toContain("收起")
  })

  it("replaces actions with the approved decision record", async () => {
    const wrapper = mountDossier(dossier({
      status: "approved",
      decision: {
        verdict: "approve",
        decided_by: "admin",
        decided_at: fixedTime,
        reject_reason: null,
        follow_id: 42,
        follow_username: "candidatea",
      },
    }))

    expect(wrapper.find("[data-testid='crq-approve-btn']").exists()).toBe(false)
    expect(wrapper.find("[data-testid='crq-reject-btn']").exists()).toBe(false)
    expect(wrapper.get("[data-testid='crq-decision-record']").text()).toContain("决策人 admin")
    await wrapper.get("[data-testid='crq-decision-record-link']").trigger("click")
    expect(push).toHaveBeenCalledWith("/follows")
  })
})
