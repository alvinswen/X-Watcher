<script setup lang="ts">
import { computed, ref } from "vue"
import { Refresh, WarningFilled } from "@element-plus/icons-vue"

const props = defineProps<{
  retry: () => Promise<unknown> | unknown
}>()

const retrying = ref(false)
const retryCount = ref(0)
const retryExhausted = computed(() => retryCount.value >= 3)
const description = computed(() => {
  if (retryExhausted.value) {
    return "请检查服务是否可用，或联系管理员"
  }
  if (retryCount.value > 0) {
    return "已重试，仍未取到数据；你可以再次重试"
  }
  return "这次没取到数据，请稍后重试"
})

async function handleRetry() {
  if (retrying.value) {
    return
  }
  retrying.value = true
  try {
    await props.retry()
  } finally {
    retryCount.value += 1
    retrying.value = false
  }
}
</script>

<template>
  <div
    class="load-error-state"
    data-empty-state="error"
    :data-retry-exhausted="retryExhausted ? 'true' : undefined"
  >
    <el-icon class="load-error-icon"><WarningFilled /></el-icon>
    <p class="load-error-title">
      {{ retryExhausted ? "多次重试仍失败" : "内容加载失败" }}
    </p>
    <p class="load-error-description">{{ description }}</p>
    <el-button
      plain
      :icon="Refresh"
      :loading="retrying"
      @click="handleRetry"
    >
      重试
    </el-button>
  </div>
</template>

<style scoped>
.load-error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 48px 20px;
  color: var(--color-danger);
  text-align: center;
}

.load-error-state > .load-error-icon {
  font-size: 56px;
  opacity: 0.85;
}

.load-error-title {
  margin: 0;
  color: var(--color-danger);
  font-family: var(--font-reading);
  font-size: var(--body-font-size);
  font-weight: 600;
}

.load-error-description {
  margin: 0;
  color: var(--text-secondary);
  font-size: var(--small-font-size);
  line-height: 1.6;
}
</style>
