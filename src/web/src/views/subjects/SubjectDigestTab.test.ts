import { defineComponent } from "vue"
import { mount } from "@vue/test-utils"
import { describe, expect, it } from "vitest"
import SubjectDigestTab from "./SubjectDigestTab.vue"
import type { SubjectDigest } from "@/types"

function digest(digestText: string): SubjectDigest {
  return {
    interval_start: "2026-08-20T00:00:00Z",
    interval_end: "2026-08-20T04:00:00Z",
    generated_at: "2026-08-20T04:01:00Z",
    tweet_count: 3,
    digest_text: digestText,
    highlights: [],
  }
}

const ElSkeletonStub = defineComponent({
  name: "ElSkeleton",
  template: "<div data-skeleton />",
})

function mountTab(loading: boolean, digests: SubjectDigest[]) {
  return mount(SubjectDigestTab, {
    props: { loading, digests },
    global: {
      stubs: {
        ElSkeleton: ElSkeletonStub,
        ElEmpty: { template: "<div v-bind='$attrs'><slot /></div>" },
        ElIcon: { template: "<span><slot /></span>" },
        ElCollapse: { template: "<div><slot /></div>" },
        ElCollapseItem: { template: "<section><slot /></section>" },
      },
    },
  })
}

describe("SubjectDigestTab", () => {
  it("renders digest text as paragraph blocks", () => {
    const wrapper = mountTab(false, [digest("第一段\n\n第二段\n\n第三段")])

    expect(wrapper.get("[data-para-count]").attributes("data-para-count")).toBe("3")
    expect(wrapper.findAll("[data-para]").map((paragraph) => paragraph.text()))
      .toEqual(["第一段", "第二段", "第三段"])
    expect(wrapper.findAll("[data-para]").map((paragraph) => paragraph.attributes("data-para")))
      .toEqual(["0", "1", "2"])
  })

  it.each(["", "   \n\n  "])("does not render a digest body container for %j", (text) => {
    const wrapper = mountTab(false, [digest(text)])

    expect(wrapper.find("[data-para-count]").exists()).toBe(false)
    expect(wrapper.find("[data-para]").exists()).toBe(false)
  })

  it("keeps the loading branch", () => {
    const wrapper = mountTab(true, [])

    expect(wrapper.findAll("[data-skeleton]")).toHaveLength(2)
    expect(wrapper.find('[data-empty-state="no-tweets"]').exists()).toBe(false)
  })

  it("keeps the empty branch", () => {
    const wrapper = mountTab(false, [])

    expect(wrapper.find('[data-empty-state="no-tweets"]').exists()).toBe(true)
    expect(wrapper.find("[data-skeleton]").exists()).toBe(false)
  })
})
