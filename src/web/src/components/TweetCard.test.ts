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
