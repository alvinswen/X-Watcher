import { defineComponent } from "vue"
import { mount } from "@vue/test-utils"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import CandidateDecisionDialog from "./CandidateDecisionDialog.vue"
import type { CandidateDossier } from "@/types"

const fixedTime = "2026-08-02T12:00:00Z"

function dossier(withAssessment = true): CandidateDossier {
  return {
    candidate_id: "candidatea",
    username: "candidatea",
    platform_user_id: "platform-42",
    status: withAssessment ? "assessed" : "discovered",
    mining: {
      citations: { source_a: { count: 3, citing_tweet_ids: ["tweet-1"] } },
      citation_total: 3,
      source_diversity: 1,
      sample_citation_tweet_ids: ["tweet-1"],
      subject_tags: [],
      first_discovered_at: fixedTime,
      last_mined_at: fixedTime,
    },
    profile_snapshot: null,
    profile_fetched_at: null,
    sample: null,
    assessment: withAssessment ? {
      scores: { originality: 8, difference: 7, expertise: 9 },
      recommendation: "，建议批准这个候选账号并持续观察",
      evidence_tweet_ids: ["sample-1"],
      assessed_at: fixedTime,
      assessed_by: "agent",
    } : null,
    decision: null,
  }
}

const ElDialogStub = defineComponent({
  name: "ElDialog",
  props: { modelValue: Boolean },
  template: `
    <section v-if="modelValue" class="dialog-stub">
      <slot name="header" />
      <slot />
      <slot name="footer" />
    </section>
  `,
})

const ElInputStub = defineComponent({
  name: "ElInput",
  inheritAttrs: false,
  props: {
    modelValue: { type: String, default: "" },
    type: { type: String, default: "text" },
    disabled: Boolean,
  },
  emits: ["update:modelValue"],
  template: `
    <textarea
      v-if="type === 'textarea'"
      v-bind="$attrs"
      :value="modelValue"
      :disabled="disabled"
      @input="$emit('update:modelValue', $event.target.value)"
    />
    <input
      v-else
      v-bind="$attrs"
      :value="modelValue"
      :disabled="disabled"
      @input="$emit('update:modelValue', $event.target.value)"
    />
  `,
})

const ElButtonStub = defineComponent({
  name: "ElButton",
  props: { disabled: Boolean, loading: Boolean },
  emits: ["click"],
  template: `
    <button :disabled="disabled || loading" @click="$emit('click')"><slot /></button>
  `,
})

function mountDialog(options: {
  decision?: "approve" | "reject"
  candidate?: CandidateDossier
  error?: string
} = {}) {
  return mount(CandidateDecisionDialog, {
    attachTo: document.body,
    props: {
      modelValue: true,
      decision: options.decision ?? "approve",
      candidate: options.candidate ?? dossier(),
      submitting: false,
      error: options.error ?? "",
    },
    global: {
      stubs: {
        ElDialog: ElDialogStub,
        ElInput: ElInputStub,
        ElButton: ElButtonStub,
        ElIcon: { template: "<span><slot /></span>" },
      },
    },
  })
}

describe("CandidateDecisionDialog", () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-08-03T12:00:00Z"))
  })

  afterEach(() => {
    document.body.innerHTML = ""
    vi.useRealTimers()
  })

  it("prefills the first ten characters without changing the assessment text", () => {
    const candidate = dossier()
    const wrapper = mountDialog({ candidate })

    expect(wrapper.get("[data-testid='crq-brief-intro-input']").attributes("value"))
      .toBe(candidate.assessment?.recommendation.slice(0, 10))
    expect(candidate.assessment?.recommendation).toBe("，建议批准这个候选账号并持续观察")

    wrapper.unmount()
  })

  it("blocks eleven Chinese characters and does not emit confirm", async () => {
    const wrapper = mountDialog()
    await wrapper.get("[data-testid='crq-brief-intro-input']")
      .setValue("一二三四五六七八九十甲")

    expect(wrapper.text()).toContain("最多 10 个汉字")
    expect(wrapper.get("[data-testid='crq-dialog-confirm']").attributes("disabled"))
      .toBeDefined()
    await wrapper.get("[data-testid='crq-dialog-confirm']").trigger("click")
    expect(wrapper.emitted("confirm")).toBeUndefined()

    wrapper.unmount()
  })

  it("keeps Enter inside inputs harmless and confirms only outside inputs", async () => {
    const approve = mountDialog()
    await approve.get("input").trigger("keydown", { key: "Enter" })
    expect(approve.emitted("confirm")).toBeUndefined()

    document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }))
    expect(approve.emitted("confirm")).toHaveLength(1)
    approve.unmount()

    const reject = mountDialog({ decision: "reject" })
    await reject.get("textarea").trigger("keydown", { key: "Enter" })
    expect(reject.emitted("confirm")).toBeUndefined()
    reject.unmount()
  })

  it("always closes on Escape, including while an input has focus", async () => {
    const wrapper = mountDialog()

    await wrapper.get("input").trigger("keydown", { key: "Escape" })

    expect(wrapper.emitted("update:modelValue")).toEqual([[false]])
    wrapper.unmount()
  })

  it("shows the direct-approve warning and keeps failed input intact", async () => {
    const wrapper = mountDialog({
      candidate: dossier(false),
      error: "批准失败：抓取名单存在同名冲突",
    })
    await wrapper.get("input").setValue("量化研究")
    await wrapper.setProps({ error: "批准失败：仍有冲突" })

    expect(wrapper.find("[data-testid='crq-direct-approve-warning']").exists()).toBe(true)
    expect(wrapper.get("[data-testid='crq-dialog-error']").text()).toContain("仍有冲突")
    expect(wrapper.get("input").attributes("value")).toBe("量化研究")

    wrapper.unmount()
  })
})
