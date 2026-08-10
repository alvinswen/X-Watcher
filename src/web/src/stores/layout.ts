import { defineStore } from "pinia"
import { ref } from "vue"

/** 跨路由保持的管理布局交互状态。 */
export const useLayoutStore = defineStore("layout", () => {
  const isFullscreen = ref(false)
  const longTweetFilterEnabled = ref(false)
  const longTweetMinLength = ref(280)
  const readingLayerEnabled = ref(false)

  return {
    isFullscreen,
    longTweetFilterEnabled,
    longTweetMinLength,
    readingLayerEnabled,
  }
})
