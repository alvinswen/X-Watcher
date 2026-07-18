import { computed, onMounted, watch } from "vue"
import { useAuthStore } from "@/stores/auth"

/** 在视图层守卫需要管理员 API Key 的加载函数。 */
export function useApiKeyGuard(load: () => void | Promise<void>) {
  const authStore = useAuthStore()
  const needsApiKey = computed(() => !authStore.isAuthenticated)

  async function loadWhenAuthenticated() {
    if (!authStore.isAuthenticated) {
      authStore.requestGuide()
      return
    }
    await load()
  }

  onMounted(() => {
    void loadWhenAuthenticated()
  })

  watch(
    () => authStore.isAuthenticated,
    (authenticated, wasAuthenticated) => {
      if (authenticated && !wasAuthenticated) {
        void load()
      }
    },
  )

  return { needsApiKey }
}
