import { afterEach, describe, expect, it } from "vitest"
import { mount, type VueWrapper } from "@vue/test-utils"
import { nextTick } from "vue"
import TweetCard from "./TweetCard.vue"
import TweetLightbox from "./TweetLightbox.vue"
import type { TweetCardData } from "@/types/tweet"

const wrappers: VueWrapper[] = []

const baseTweet = {
  tweet_id: "tweet-1",
  created_at: "2026-08-06T08:20:44Z",
  author_username: "marclou",
  author_display_name: "Marc Lou",
  summary_text: "一条摘要",
  translation_text: "一条翻译",
  text: "An original tweet",
  reference_type: null,
  referenced_tweet_id: null,
  referenced_tweet_text: null,
  referenced_tweet_author_username: null,
  media: [{ type: "photo", url: "https://example.test/image.jpg", width: 1200, height: 675 }],
  referenced_tweet_media: [],
} as TweetCardData

function trackedMount(component: Parameters<typeof mount>[0], options: Parameters<typeof mount>[1]) {
  const wrapper = mount(component, options) as VueWrapper
  wrappers.push(wrapper)
  return wrapper
}

afterEach(() => {
  for (const wrapper of wrappers.splice(0)) wrapper.unmount()
  document.body.innerHTML = ""
  document.body.style.overflow = ""
})

describe("TweetLightbox", () => {
  it("moves from loading to ok and restores scroll plus focus", async () => {
    const trigger = document.createElement("button")
    document.body.appendChild(trigger)
    trigger.focus()
    const wrapper = trackedMount(TweetLightbox, {
      props: { src: "https://example.test/image.jpg" },
      attachTo: document.body,
    })

    expect(document.body.style.overflow).toBe("hidden")
    expect(document.body.querySelector('[data-testid="tweet-lightbox"]')?.getAttribute("data-state")).toBe("loading")

    document.body.querySelector<HTMLImageElement>('[data-testid="tweet-lightbox"] img')
      ?.dispatchEvent(new Event("load"))
    await nextTick()
    expect(document.body.querySelector('[data-testid="tweet-lightbox"]')?.getAttribute("data-state")).toBe("ok")

    wrapper.unmount()
    await nextTick()
    expect(document.body.style.overflow).toBe("")
    expect(document.activeElement).toBe(trigger)
  })

  it("exposes an error state and emits close on Escape", async () => {
    const wrapper = trackedMount(TweetLightbox, {
      props: { src: "https://example.test/broken.jpg" },
      attachTo: document.body,
    })
    document.body.querySelector<HTMLImageElement>('[data-testid="tweet-lightbox"] img')
      ?.dispatchEvent(new Event("error"))
    await nextTick()

    expect(document.body.querySelector('[data-testid="tweet-lightbox"]')?.getAttribute("data-state")).toBe("error")
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }))
    expect(wrapper.emitted("close")).toHaveLength(1)
  })
})

describe("TweetCard lightbox integration", () => {
  it("opens from existing media without emitting the card click", async () => {
    const wrapper = trackedMount(TweetCard, {
      props: { tweet: baseTweet, clickable: true },
      attachTo: document.body,
      global: { stubs: { ElButton: true, ElIcon: true } },
    })

    const media = wrapper.get('[data-testid="tweet-card-media-item"] img')
    expect(media.attributes("width")).toBe("1200")
    expect(media.attributes("height")).toBe("675")
    await media.trigger("click")
    expect(wrapper.emitted("click")).toBeUndefined()
    expect(document.body.querySelector('[data-testid="tweet-lightbox"]')).not.toBeNull()

    document.body.querySelector<HTMLElement>('[data-testid="tweet-lightbox"]')?.click()
    await nextTick()
    expect(document.body.querySelector('[data-testid="tweet-lightbox"]')).toBeNull()
  })

  it("renders the video badge and replaces only a failed tile", async () => {
    const wrapper = trackedMount(TweetCard, {
      props: {
        tweet: {
          ...baseTweet,
          media: [
            { type: "video", url: "https://example.test/video.jpg", width: 800, height: 1000 },
            { type: "photo", url: "https://example.test/ok.jpg", width: 1200, height: 675 },
          ],
        } as TweetCardData,
      },
      global: { stubs: { ElButton: true, ElIcon: true } },
    })

    expect(wrapper.get('[data-testid="tweet-card-media-video-badge"]').text()).toBe("▶ 视频封面")
    await wrapper.findAll('[data-testid="tweet-card-media-item"] img')[0]!.trigger("error")
    expect(wrapper.findAll('[data-testid="tweet-card-media-broken"]')).toHaveLength(1)
    expect(wrapper.findAll('[data-testid="tweet-card-media-item"] img')).toHaveLength(1)
  })

  it("keeps referenced media hidden by default and exposes it through its own prop", async () => {
    const tweet = {
      ...baseTweet,
      referenced_tweet_id: "quoted-1",
      referenced_tweet_text: "Quoted text",
      referenced_tweet_author_username: "quoted_author",
      referenced_tweet_media: [
        { type: "photo", url: "https://example.test/quoted.jpg", width: 600, height: 400 },
      ],
    } as TweetCardData
    const wrapper = trackedMount(TweetCard, {
      props: { tweet, collapsibleOriginal: true },
      global: { stubs: { ElButton: true, ElIcon: true } },
    })

    expect(wrapper.find('[data-testid="tweet-card-ref-media-item"]').exists()).toBe(false)
    await wrapper.setProps({ showRefMedia: true })
    expect(wrapper.find('[data-testid="tweet-card-ref-media-item"]').exists()).toBe(true)
  })
})

describe("TweetCard reading mode", () => {
  it("independently expands and collapses the translation and original layers", async () => {
    const wrapper = trackedMount(TweetCard, {
      props: { tweet: { ...baseTweet, media: [] } as TweetCardData, readingMode: true },
      global: { stubs: { ElButton: true, ElIcon: true } },
    })
    const buttons = wrapper.findAll('[data-testid="tweet-card-layer-btn"]')
    expect(buttons.map((button) => button.text())).toEqual(["▸ 全文", "▸ 原文"])

    await buttons[0]!.trigger("click")
    expect(buttons[0]!.text()).toBe("▾ 收起全文")
    expect(buttons[0]!.attributes("aria-expanded")).toBe("true")
    expect(wrapper.get('[data-testid="tweet-card-layer-trans"]').text()).toBe("一条翻译")
    expect(wrapper.find('[data-testid="tweet-card-layer-orig"]').exists()).toBe(false)

    await buttons[1]!.trigger("click")
    expect(buttons[1]!.text()).toBe("▾ 收起原文")
    expect(wrapper.get('[data-testid="tweet-card-layer-orig"]').text()).toContain("An original tweet")

    await buttons[0]!.trigger("click")
    expect(wrapper.find('[data-testid="tweet-card-layer-trans"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="tweet-card-layer-orig"]').exists()).toBe(true)
  })

  it("omits the translation button when translation is absent or the original is Chinese", () => {
    const withoutTranslation = trackedMount(TweetCard, {
      props: {
        tweet: { ...baseTweet, media: [], translation_text: null } as TweetCardData,
        readingMode: true,
      },
      global: { stubs: { ElButton: true, ElIcon: true } },
    })
    expect(withoutTranslation.find('[data-layer="trans"]').exists()).toBe(false)

    const chineseOriginal = trackedMount(TweetCard, {
      props: {
        tweet: { ...baseTweet, media: [], text: "汉汉汉xxxxxxxxxxxxxxxxx" } as TweetCardData,
        readingMode: true,
      },
      global: { stubs: { ElButton: true, ElIcon: true } },
    })
    expect(chineseOriginal.find('[data-layer="trans"]').exists()).toBe(false)
    expect(chineseOriginal.get('[data-layer="orig"]').text()).toBe("▸ 原文")
  })

  it("uses the original as L1 when the summary is absent without duplicating it", async () => {
    const wrapper = trackedMount(TweetCard, {
      props: {
        tweet: { ...baseTweet, media: [], summary_text: null } as TweetCardData,
        readingMode: true,
      },
      global: { stubs: { ElButton: true, ElIcon: true } },
    })
    expect(wrapper.get('[data-testid="tweet-card-summary-line"]').text()).toBe("An original tweet")
    expect(wrapper.find('[data-layer="orig"]').exists()).toBe(false)

    await wrapper.setProps({
      tweet: {
        ...baseTweet,
        media: [],
        summary_text: null,
        referenced_tweet_id: "quoted-1",
        referenced_tweet_text: "Quoted only",
      } as TweetCardData,
    })
    expect(wrapper.find('[data-layer="orig"]').exists()).toBe(true)
  })

  it("distinguishes a fully empty card from an empty card with a quote", async () => {
    const wrapper = trackedMount(TweetCard, {
      props: {
        tweet: { ...baseTweet, media: [], summary_text: null, text: "", translation_text: null } as TweetCardData,
        readingMode: true,
      },
      global: { stubs: { ElButton: true, ElIcon: true } },
    })
    expect(wrapper.get('[data-testid="tweet-card-empty"]').text()).toBe("该推文无正文内容")
    expect(wrapper.findAll('[data-testid="tweet-card-layer-btn"]')).toHaveLength(0)

    await wrapper.setProps({
      tweet: {
        ...baseTweet,
        media: [],
        summary_text: null,
        text: "",
        translation_text: null,
        referenced_tweet_id: "quoted-1",
        referenced_tweet_text: "Quoted only",
      } as TweetCardData,
    })
    expect(wrapper.get('[data-testid="tweet-card-empty"]').exists()).toBe(true)
    await wrapper.get('[data-layer="orig"]').trigger("click")
    expect(wrapper.get('[data-testid="tweet-card-ref-quote"]').text()).toContain("Quoted only")
    expect(wrapper.find(".layer-text").exists()).toBe(false)
  })

  it("renders a relation without a bare at-sign when the quoted author is missing", () => {
    const wrapper = trackedMount(TweetCard, {
      props: {
        tweet: {
          ...baseTweet,
          media: [],
          reference_type: "replied_to",
          referenced_tweet_id: "quoted-1",
          referenced_tweet_author_username: null,
        } as TweetCardData,
        readingMode: true,
      },
      global: { stubs: { ElButton: true, ElIcon: true } },
    })
    expect(wrapper.get('[data-testid="tweet-card-rel-tag"]').text()).toBe("回复")
  })

  it("preserves the legacy review markup when reading mode is off", () => {
    const wrapper = trackedMount(TweetCard, {
      props: { tweet: { ...baseTweet, media: [] } as TweetCardData },
      global: { stubs: { ElButton: true, ElIcon: true } },
    })
    expect(wrapper.get('[data-testid="tweet-card-summary-label"]').text()).toBe("摘要")
    expect(wrapper.get('[data-testid="tweet-card-translation"]').text()).toBe("一条翻译")
    expect(wrapper.get(".original-section").text()).toContain("An original tweet")
    expect(wrapper.find('[data-testid="tweet-card-layer-btn"]').exists()).toBe(false)
  })

  it("auto-expands a matching hidden layer and renders safe highlight segments", () => {
    const wrapper = trackedMount(TweetCard, {
      props: {
        tweet: { ...baseTweet, media: [], translation_text: "Agent 的中文全文" } as TweetCardData,
        readingMode: true,
        highlightTerms: ["agent"],
      },
      global: { stubs: { ElButton: true, ElIcon: true } },
    })
    expect(wrapper.get('[data-layer="trans"]').text()).toBe("▾ 收起全文")
    expect(wrapper.get('[data-testid="tweet-card-layer-trans"]').text()).toBe("Agent 的中文全文")
    expect(wrapper.get('[data-testid="tweet-card-hit"]').text()).toBe("Agent")
  })

  it("keeps hidden layers collapsed when the match is visible in the summary", () => {
    const wrapper = trackedMount(TweetCard, {
      props: {
        tweet: { ...baseTweet, media: [], summary_text: "Visible agent summary" } as TweetCardData,
        readingMode: true,
        highlightTerms: ["agent"],
      },
      global: { stubs: { ElButton: true, ElIcon: true } },
    })
    expect(wrapper.get('[data-testid="tweet-card-hit"]').text()).toBe("agent")
    expect(wrapper.find('[data-testid="tweet-card-layer-trans"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="tweet-card-layer-orig"]').exists()).toBe(false)
  })

  it("recomputes expansion when search terms or the tweet change", async () => {
    const wrapper = trackedMount(TweetCard, {
      props: {
        tweet: { ...baseTweet, media: [], text: "Original needle" } as TweetCardData,
        readingMode: true,
        highlightTerms: ["needle"],
      },
      global: { stubs: { ElButton: true, ElIcon: true } },
    })
    expect(wrapper.find('[data-testid="tweet-card-layer-orig"]').exists()).toBe(true)

    await wrapper.setProps({ highlightTerms: ["一条摘要"] })
    expect(wrapper.find('[data-testid="tweet-card-layer-orig"]').exists()).toBe(false)

    await wrapper.setProps({
      tweet: { ...baseTweet, tweet_id: "tweet-2", media: [], translation_text: "second hit" } as TweetCardData,
      highlightTerms: ["second"],
    })
    expect(wrapper.find('[data-testid="tweet-card-layer-trans"]').exists()).toBe(true)
  })

  it("keeps the unstripped summary when its prefix contains the visible search hit", () => {
    const wrapper = trackedMount(TweetCard, {
      props: {
        tweet: {
          ...baseTweet,
          media: [],
          author_username: "a",
          summary_text: "@a 引用 @b：找 keyword 的话",
        } as TweetCardData,
        readingMode: true,
        highlightTerms: ["@b"],
      },
      global: { stubs: { ElButton: true, ElIcon: true } },
    })
    expect(wrapper.get('[data-testid="tweet-card-summary-line"]').text()).toBe("@a 引用 @b：找 keyword 的话")
  })

  it("renders script-like content as text and never as executable markup", () => {
    const wrapper = trackedMount(TweetCard, {
      props: {
        tweet: { ...baseTweet, media: [], summary_text: "<script>alert(1)</script>" } as TweetCardData,
        readingMode: true,
        highlightTerms: ["script"],
      },
      global: { stubs: { ElButton: true, ElIcon: true } },
    })
    expect(wrapper.get('[data-testid="tweet-card-summary-line"]').text()).toBe("<script>alert(1)</script>")
    expect(wrapper.find("script").exists()).toBe(false)
  })

  it("blocks card clicks from layer buttons while retaining the blank-card action", async () => {
    const wrapper = trackedMount(TweetCard, {
      props: { tweet: { ...baseTweet, media: [] } as TweetCardData, readingMode: true, clickable: true },
      global: { stubs: { ElButton: true, ElIcon: true } },
    })
    await wrapper.get('[data-layer="trans"]').trigger("click")
    expect(wrapper.emitted("click")).toBeUndefined()
    await wrapper.get('[data-testid="tweet-card"]').trigger("click")
    expect(wrapper.emitted("click")).toEqual([["tweet-1"]])
  })
})
