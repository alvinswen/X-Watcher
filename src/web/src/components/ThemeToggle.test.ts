import { beforeEach, describe, expect, it } from "vitest"
import { createPinia, setActivePinia } from "pinia"
import { mount } from "@vue/test-utils"
import { Monitor, Moon, Sunny } from "@element-plus/icons-vue"
import ThemeToggle from "@/components/ThemeToggle.vue"
import { useThemeStore } from "@/stores/theme"

function mountToggle(testid?: string) {
  return mount(ThemeToggle, {
    props: testid ? { testid } : {},
    global: {
      stubs: {
        ElIcon: { template: "<span><slot /></span>" },
      },
    },
  })
}

describe("ThemeToggle", () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
    useThemeStore().setMode("light")
  })

  it("按亮色、暗色、跟随系统循环并同步图标与标题", async () => {
    const wrapper = mountToggle()
    const button = wrapper.get("[data-testid='theme-toggle']")

    expect(button.attributes("title")).toBe("亮色模式")
    expect(wrapper.findComponent(Sunny).exists()).toBe(true)

    await button.trigger("click")
    expect(button.attributes("title")).toBe("暗色模式")
    expect(wrapper.findComponent(Moon).exists()).toBe(true)

    await button.trigger("click")
    expect(button.attributes("title")).toBe("跟随系统")
    expect(wrapper.findComponent(Monitor).exists()).toBe(true)

    await button.trigger("click")
    expect(button.attributes("title")).toBe("亮色模式")
    expect(wrapper.findComponent(Sunny).exists()).toBe(true)
  })

  it("支持全屏工具条的独立 testid", () => {
    const wrapper = mountToggle("theme-toggle-fullscreen")
    expect(wrapper.get("[data-testid='theme-toggle-fullscreen']").attributes("aria-label"))
      .toBe("主题切换：当前亮色模式")
  })
})
