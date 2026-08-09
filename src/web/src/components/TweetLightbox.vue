<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue"

const props = defineProps<{
  src: string
}>()

const emit = defineEmits<{
  close: []
}>()

const state = ref<"loading" | "ok" | "error">("loading")
let previousOverflow = ""
let previousFocus: HTMLElement | null = null

watch(() => props.src, () => {
  state.value = "loading"
})

function handleKeydown(event: KeyboardEvent) {
  if (event.key !== "Escape") return
  event.stopPropagation()
  emit("close")
}

onMounted(() => {
  previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
  previousOverflow = document.body.style.overflow
  document.body.style.overflow = "hidden"
  document.addEventListener("keydown", handleKeydown, { capture: true })
})

onBeforeUnmount(() => {
  document.body.style.overflow = previousOverflow
  document.removeEventListener("keydown", handleKeydown, { capture: true })
  queueMicrotask(() => previousFocus?.focus())
})
</script>

<template>
  <Teleport to="body">
    <div
      class="tweet-lightbox"
      data-testid="tweet-lightbox"
      :data-state="state"
      role="dialog"
      aria-modal="true"
      aria-label="图片放大"
      @click="emit('close')"
    >
      <div v-if="state === 'loading'" class="lightbox-state">
        <span class="lightbox-spinner" />
        <span>图片加载中…</span>
      </div>
      <div v-if="state === 'error'" class="lightbox-state">
        <span class="lightbox-error-icon">⊘</span>
        <span>图片加载失败</span>
        <span class="lightbox-error-hint">点任意处或按 Esc 关闭</span>
      </div>
      <img
        v-show="state === 'ok'"
        :src="src"
        alt="放大图片"
        @load="state = 'ok'"
        @error="state = 'error'"
      >
      <span class="lightbox-hint">点击任意处关闭 · Esc</span>
    </div>
  </Teleport>
</template>

<style scoped>
.tweet-lightbox {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px;
  overflow: hidden;
  overscroll-behavior: contain;
  background: var(--lightbox-mask);
  cursor: zoom-out;
}

.tweet-lightbox img {
  max-width: 96vw;
  max-height: 92vh;
  border-radius: var(--el-border-radius-base);
  box-shadow: 0 8px 40px rgba(44, 36, 23, 0.5);
  filter: none !important;
}

.lightbox-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  font-family: var(--font-ui);
  font-size: var(--reading-font-size);
  color: rgba(255, 255, 255, 0.8);
}

.lightbox-spinner {
  width: 28px;
  height: 28px;
  border: 2px solid rgba(255, 255, 255, 0.25);
  border-top-color: rgba(255, 255, 255, 0.85);
  border-radius: 50%;
  animation: lightbox-spin 0.8s linear infinite;
}

.lightbox-error-icon {
  font-size: 24px;
}

.lightbox-error-hint {
  font-size: var(--xs-font-size);
  color: rgba(255, 255, 255, 0.55);
}

.lightbox-hint {
  position: absolute;
  bottom: 16px;
  left: 50%;
  transform: translateX(-50%);
  font-family: var(--font-mono);
  font-size: var(--label-font-size);
  color: rgba(255, 255, 255, 0.55);
}

@keyframes lightbox-spin {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .lightbox-spinner { animation: none !important; }
}
</style>
