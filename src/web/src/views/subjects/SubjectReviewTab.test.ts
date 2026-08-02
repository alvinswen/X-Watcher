import { defineComponent, inject, provide } from "vue"
import { mount } from "@vue/test-utils"
import { beforeEach, describe, expect, it, vi } from "vitest"
import SubjectReviewTab from "./SubjectReviewTab.vue"
import { formatAbsoluteDateTime } from "./subjectFormat"
import type { SubjectReview, SubjectReviewHistoryItem, TweetCardData } from "@/types"

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

const dropdownCommandKey = Symbol("dropdown-command")

const ElDropdownStub = defineComponent({
  name: "ElDropdown",
  emits: ["command", "visible-change"],
  setup(_, { emit }) {
    provide(dropdownCommandKey, (value: number) => emit("command", value))
    return { open: () => emit("visible-change", true) }
  },
  template: `
    <div class="el-dropdown-stub">
      <div class="el-dropdown-trigger-stub" @click="open"><slot /></div>
      <div class="el-dropdown-content-stub"><slot name="dropdown" /></div>
    </div>
  `,
})

const ElDropdownMenuStub = defineComponent({
  name: "ElDropdownMenu",
  template: "<div><slot /></div>",
})

const ElDropdownItemStub = defineComponent({
  name: "ElDropdownItem",
  props: {
    command: { type: Number, required: true },
  },
  setup(props) {
    const sendCommand = inject<(value: number) => void>(dropdownCommandKey)
    return { select: () => sendCommand?.(props.command) }
  },
  template: "<button type='button' @click='select'><slot /></button>",
})

interface MountTabOptions {
  error?: string
  retryReview?: () => Promise<unknown>
  loading?: boolean
  version?: number
  latestVersion?: number
  viewingVersion?: number | null
  viewLoading?: boolean
  historyItems?: SubjectReviewHistoryItem[]
  historyLoading?: boolean
  historyError?: string
}

function mountTab(options: MountTabOptions = {}) {
  const nextReview = review()
  return mount(SubjectReviewTab, {
    props: {
      loading: options.loading ?? false,
      review: nextReview,
      version: options.version ?? nextReview.version,
      latestVersion: options.latestVersion ?? nextReview.version,
      viewingVersion: options.viewingVersion ?? null,
      viewLoading: options.viewLoading ?? false,
      historyItems: options.historyItems ?? [],
      historyLoading: options.historyLoading ?? false,
      historyError: options.historyError ?? "",
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
        ElIcon: { template: "<span><slot /></span>" },
        ElDropdown: ElDropdownStub,
        ElDropdownMenu: ElDropdownMenuStub,
        ElDropdownItem: ElDropdownItemStub,
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

  it("renders history trigger with arrow when version >= 1", () => {
    const wrapper = mountTab()

    expect(wrapper.find("[data-review-history-trigger]").exists()).toBe(true)
    expect(wrapper.find(".badge-arrow").exists()).toBe(true)
  })

  it("hides history trigger at v0", () => {
    const wrapper = mountTab({ version: 0, latestVersion: 0 })

    expect(wrapper.find("[data-review-history-trigger]").exists()).toBe(false)
    expect(wrapper.get('[data-review-version-badge="0"]').classes()).toContain("empty")
  })

  it("renders history items in given order with exactly one current mark", () => {
    const historyItems: SubjectReviewHistoryItem[] = [
      { version: 3, generated_at: "2026-07-03T12:00:00Z", generated_by: "llm" },
      { version: 2, generated_at: "2026-07-02T12:00:00Z", generated_by: "fallback" },
      { version: 1, generated_at: "2026-07-01T12:00:00Z", generated_by: "skill" },
    ]
    const wrapper = mountTab({ version: 2, latestVersion: 3, historyItems })

    expect(wrapper.findAll("[data-review-history-item]").map((item) => (
      item.attributes("data-review-history-item")
    ))).toEqual(["3", "2", "1"])
    expect(wrapper.findAll("[data-review-history-current]")).toHaveLength(1)
    expect(wrapper.text().match(/降级生成/g)).toHaveLength(1)
  })

  it("shows absolute datetime title on item time", () => {
    const generatedAt = "2026-07-03T12:00:00Z"
    const wrapper = mountTab({
      historyItems: [{ version: 1, generated_at: generatedAt, generated_by: "skill" }],
    })

    expect(wrapper.get(".history-time").attributes("title"))
      .toBe(formatAbsoluteDateTime(generatedAt))
  })

  it("emits select-version for history item and back-latest for current item", async () => {
    const wrapper = mountTab({
      version: 2,
      latestVersion: 3,
      viewingVersion: 2,
      historyItems: [
        { version: 3, generated_at: null, generated_by: "llm" },
        { version: 2, generated_at: null, generated_by: "skill" },
      ],
    })

    await wrapper.get('[data-review-history-item="2"]').trigger("click")
    await wrapper.get('[data-review-history-item="3"]').trigger("click")

    expect(wrapper.emitted("select-version")).toEqual([[2]])
    expect(wrapper.emitted("back-latest")).toEqual([[]])
  })

  it("shows viewing banner with version and emits back-latest", async () => {
    const wrapper = mountTab({ version: 3, latestVersion: 7, viewingVersion: 3 })

    expect(wrapper.get('[data-review-viewing="3"]').text()).toContain("历史版 v3")
    await wrapper.get("[data-review-back-latest]").trigger("click")
    expect(wrapper.emitted("back-latest")).toEqual([[]])
  })

  it("keeps banner while error state shown", () => {
    const wrapper = mountTab({
      version: 3,
      latestVersion: 7,
      viewingVersion: 3,
      error: "综述加载失败",
    })

    expect(wrapper.find('[data-review-viewing="3"]').exists()).toBe(true)
    expect(wrapper.find('[data-empty-state="error"]').exists()).toBe(true)
  })

  it("shows skeleton with banner during view loading", () => {
    const wrapper = mountTab({
      version: 3,
      latestVersion: 7,
      viewingVersion: 3,
      viewLoading: true,
    })

    expect(wrapper.find('[data-review-viewing="3"]').exists()).toBe(true)
    expect(wrapper.findAll(".review-skeleton")).toHaveLength(2)
  })
})
