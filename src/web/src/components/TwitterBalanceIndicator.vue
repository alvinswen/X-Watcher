<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue"
import { Coin, Refresh, Warning } from "@element-plus/icons-vue"
import { ElMessage } from "element-plus"
import { statusApi } from "@/api/status"
import type { TwitterBalanceResponse } from "@/types/status"

const POLL_INTERVAL_MS = 600_000 // 10 分钟，与后端缓存对齐

const balance = ref<TwitterBalanceResponse | null>(null)
const loading = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

async function fetchBalance(force = false, silent = true) {
  loading.value = true
  try {
    balance.value = await statusApi.getTwitterBalance(force, {
      suppressErrorToast: silent,
    })
  } catch (e: unknown) {
    // 网络/权限错误不要打扰用户，只静默标记错误
    balance.value = {
      recharge_credits: null,
      fetched_at: null,
      source: "error",
      error: e instanceof Error ? e.message : String(e),
      warning_threshold: 50000,
      danger_threshold: 10000,
    }
  } finally {
    loading.value = false
  }
}

async function manualRefresh() {
  await fetchBalance(true, false)
  if (balance.value && balance.value.source === "live") {
    ElMessage.success("余额已刷新")
  } else if (balance.value?.error) {
    ElMessage.warning(`余额刷新失败：${balance.value.error}`)
  }
}

/** 显示级别：normal | warning | danger | unknown */
const level = computed<"normal" | "warning" | "danger" | "unknown">(() => {
  const b = balance.value
  if (!b || b.recharge_credits === null) return "unknown"
  if (b.recharge_credits < b.danger_threshold) return "danger"
  if (b.recharge_credits < b.warning_threshold) return "warning"
  return "normal"
})

const formatted = computed(() => {
  const credits = balance.value?.recharge_credits
  if (credits === null || credits === undefined) return "—"
  return credits.toLocaleString("en-US")
})

const tooltipText = computed(() => {
  const b = balance.value
  if (!b) return "正在查询余额…"
  if (b.recharge_credits === null) {
    return `余额未知：${b.error ?? "无法获取"}`
  }
  const fetched = b.fetched_at ? new Date(b.fetched_at).toLocaleString("zh-CN") : "未知"
  const sourceLabel = {
    live: "刚刚获取",
    cache: "缓存数据",
    stale: `读取失败，显示上次成功结果`,
    error: "查询失败",
  }[b.source]

  if (level.value === "danger") {
    return `余额不足！剩余 ${formatted.value} credits，请尽快前往 https://twitterapi.io/dashboard 续费\n更新时间：${fetched}（${sourceLabel}）`
  }
  if (level.value === "warning") {
    return `余额偏低，剩余 ${formatted.value} credits，建议尽快续费\n更新时间：${fetched}（${sourceLabel}）`
  }
  return `TwitterAPI.io 余额：${formatted.value} credits\n更新时间：${fetched}（${sourceLabel}）`
})

onMounted(() => {
  fetchBalance()
  pollTimer = setInterval(() => fetchBalance(), POLL_INTERVAL_MS)
})

onUnmounted(() => {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})
</script>

<template>
  <el-tooltip :content="tooltipText" placement="bottom" :show-after="200">
    <div
      class="balance-indicator"
      :class="`level-${level}`"
      @click="manualRefresh"
    >
      <el-icon class="balance-icon">
        <Warning v-if="level === 'danger' || level === 'warning'" />
        <Coin v-else />
      </el-icon>
      <span class="balance-text">
        <template v-if="level === 'unknown'">余额未知</template>
        <template v-else>{{ formatted }}</template>
      </span>
      <el-icon v-if="loading" class="balance-refresh spinning"><Refresh /></el-icon>
    </div>
  </el-tooltip>
</template>

<style scoped>
.balance-indicator {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 13px;
  font-family: var(--font-mono, monospace);
  cursor: pointer;
  transition: background-color var(--transition-base, 0.2s);
  user-select: none;
}

.balance-indicator:hover {
  background-color: var(--bg-hover, rgba(0, 0, 0, 0.04));
}

.balance-icon {
  font-size: 14px;
}

.balance-text {
  font-weight: 500;
}

.level-normal {
  color: var(--color-success, #4a7c59);
}

.level-warning {
  color: var(--color-warning, #c8941a);
  font-weight: 600;
}

.level-danger {
  color: var(--color-danger, #c0392b);
  font-weight: 700;
}

.level-unknown {
  color: var(--text-tertiary, #999);
}

.balance-refresh {
  font-size: 12px;
  color: var(--text-tertiary, #999);
}

.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
