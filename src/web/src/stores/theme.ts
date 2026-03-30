import { defineStore } from "pinia"
import { ref, watch } from "vue"

export type ThemeMode = "light" | "dark" | "system"

const STORAGE_KEY = "x-watcher-theme"

export const useThemeStore = defineStore("theme", () => {
  const mode = ref<ThemeMode>(
    (localStorage.getItem(STORAGE_KEY) as ThemeMode) || "system",
  )

  const systemDark = ref(
    window.matchMedia("(prefers-color-scheme: dark)").matches,
  )

  /** 当前是否处于暗色 */
  function isDark(): boolean {
    return mode.value === "dark" || (mode.value === "system" && systemDark.value)
  }

  /** 应用主题到 <html> */
  function apply() {
    document.documentElement.classList.toggle("dark", isDark())
  }

  /** 切换主题 */
  function toggle() {
    if (mode.value === "light") mode.value = "dark"
    else if (mode.value === "dark") mode.value = "system"
    else mode.value = "light"
  }

  /** 设置主题 */
  function setMode(m: ThemeMode) {
    mode.value = m
  }

  // 监听系统主题变化
  window
    .matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", (e) => {
      systemDark.value = e.matches
      if (mode.value === "system") apply()
    })

  // 持久化 + 应用
  watch(mode, (val) => {
    localStorage.setItem(STORAGE_KEY, val)
    apply()
  }, { immediate: true })

  return { mode, isDark, toggle, setMode, apply }
})
