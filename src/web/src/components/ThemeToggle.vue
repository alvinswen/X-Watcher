<script setup lang="ts">
import { computed } from "vue"
import { Moon, Sunny, Monitor } from "@element-plus/icons-vue"
import { useThemeStore } from "@/stores/theme"

const props = withDefaults(defineProps<{ testid?: string }>(), { testid: "theme-toggle" })
const themeStore = useThemeStore()
const title = computed(() =>
  themeStore.mode === "light" ? "亮色模式" : themeStore.mode === "dark" ? "暗色模式" : "跟随系统",
)
</script>

<template>
  <button
    class="theme-toggle"
    type="button"
    :data-testid="props.testid"
    :title="title"
    :aria-label="`主题切换：当前${title}`"
    @click="themeStore.toggle()"
  >
    <el-icon :size="18">
      <Sunny v-if="themeStore.mode === 'light'" />
      <Moon v-else-if="themeStore.mode === 'dark'" />
      <Monitor v-else />
    </el-icon>
  </button>
</template>

<style scoped>
/* 真因结构约束：padding 在 button，el-icon 不带 padding */
.theme-toggle {
  display: inline-flex; align-items: center; justify-content: center;
  padding: 6px 8px; border: none; background: transparent; cursor: pointer;
  border-radius: var(--el-border-radius-base);
  color: var(--text-secondary);
  transition: color var(--transition-base), background-color var(--transition-base);
}
.theme-toggle:hover { color: var(--text-primary); background-color: var(--bg-inset); }
.theme-toggle:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 1px; }
</style>
