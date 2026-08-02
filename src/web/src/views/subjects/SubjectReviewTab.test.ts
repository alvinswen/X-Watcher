import { defineComponent } from "vue"
import { mount } from "@vue/test-utils"
import { beforeEach, describe, expect, it, vi } from "vitest"
import SubjectReviewTab from "./SubjectReviewTab.vue"
import type { SubjectReview, TweetCardData } from "@/types"

const { push } = vi.hoisted(() => ({ push: vi.fn() }))

vi.mock("vue-router", () => ({
  useRouter: () => ({ push }),
}))

const ids = ["9100000000000000001", "9100000000000000404", "9100000000000000002"]

function card(tweetId: string): TweetCardData {
  return {
    tweet_id: tweetId,
    text: `tweet ${tweetId}`,
    created_at: "2026-07-01T12:00:00Z",
    author_username: "author",
    author_display_name: "Author",
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

function review(): SubjectReview {
  return {
    subject_id: "sub_review",
    version: 1,
    sections: [{ title: "论点一", body: "正文一", cited_tweet_ids: ids }],
    trend: { emerging: [], fading: [] },
    cited_tweet_ids: ids,
    cited_tweets: [card(ids[0]), card(ids[2])],
    missing_tweet_ids: [ids[1]],
  }
}

const TweetCardStub = defineComponent({
  name: "TweetCard",
  props: {
    tweet: { type: Object, required: true },
  },
  emits: ["click"],
  template: `
    <button class="tweet-card-stub" @click="$emit('click', tweet.tweet_id)">
      {{ tweet.tweet_id }}
    </button>
  `,
})

const LoadErrorStateStub = defineComponent({
  name: "LoadErrorState",
  props: {
    retry: { type: Function, required: true },
  },
  template: `
    <div data-empty-state="error">
      <button data-retry @click="retry()">重试</button>
    </div>
  `,
})

function mountTab(options: { error?: string; retryReview?: () => Promise<unknown> } = {}) {
  const nextReview = review()
  return mount(SubjectReviewTab, {
    props: {
      loading: false,
      review: nextReview,
      version: nextReview.version,
      sections: nextReview.sections,
      hasTrend: false,
      error: options.error ?? "",
      pending: false,
      refreshing: false,
      requestButtonText: "请求更新综述",
      updatedText: "刚刚更新",
      openSections: ["0"],
      openCites: ["cite-0"],
      retryReview: options.retryReview ?? vi.fn().mockResolvedValue(undefined),
    },
    global: {
      stubs: {
        TweetCard: TweetCardStub,
        LoadErrorState: LoadErrorStateStub,
        ElCollapse: { template: "<div><slot /></div>" },
        ElCollapseItem: { template: "<section><slot name='title' /><slot /></section>" },
        ElButton: { template: "<button><slot /></button>" },
        ElTag: { template: "<span><slot /></span>" },
      },
    },
  })
}

describe("SubjectReviewTab citation cards", () => {
  beforeEach(() => {
    push.mockReset()
  })

  it("keeps card plus missing-row count equal to the cited id count", () => {
    const wrapper = mountTab()

    expect(wrapper.findAll("[data-cite-tweet-id]")).toHaveLength(2)
    expect(wrapper.findAll("[data-cite-missing-id]")).toHaveLength(1)
    expect(
      wrapper.findAll("[data-cite-tweet-id], [data-cite-missing-id]"),
    ).toHaveLength(ids.length)
  })

  it("renders cards and missing rows in section id order", () => {
    const wrapper = mountTab()
    const children = Array.from(wrapper.get(".review-cite-panel").element.children)

    expect(children.map((element) => (
      element.getAttribute("data-cite-tweet-id")
      ?? element.getAttribute("data-cite-missing-id")
    ))).toEqual(ids)
  })

  it("navigates to tweet detail when a card is clicked", async () => {
    const wrapper = mountTab()

    await wrapper.get(`[data-cite-tweet-id="${ids[0]}"]`).trigger("click")

    expect(push).toHaveBeenCalledOnce()
    expect(push).toHaveBeenCalledWith(`/tweets/${ids[0]}`)
  })

  it("does not navigate when a missing row is clicked", async () => {
    const wrapper = mountTab()

    await wrapper.get(`[data-cite-missing-id="${ids[1]}"]`).trigger("click")

    expect(push).not.toHaveBeenCalled()
  })

  it("keeps the cited-id container hook", () => {
    const wrapper = mountTab()

    expect(wrapper.get("[data-cited-tweet-ids]").attributes("data-cited-tweet-ids"))
      .toBe(ids.join(","))
  })

  it("uses the unified error state and retries the review request", async () => {
    const retryReview = vi.fn().mockResolvedValue(undefined)
    const wrapper = mountTab({ error: "综述加载失败", retryReview })

    expect(wrapper.find('[data-empty-state="error"]').exists()).toBe(true)
    expect(wrapper.find(".review-error").exists()).toBe(false)
    await wrapper.get("[data-retry]").trigger("click")
    expect(retryReview).toHaveBeenCalledOnce()
  })
})
