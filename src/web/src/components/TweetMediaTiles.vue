<script setup lang="ts">
import { ref, watch } from "vue"
import type { MediaItem } from "@/types/tweet"

const props = withDefaults(defineProps<{
  items: MediaItem[]
  variant?: "main" | "ref"
  hoverZoom?: boolean
}>(), {
  variant: "main",
  hoverZoom: false,
})

const emit = defineEmits<{
  zoom: [src: string]
}>()

const broken = ref<Record<number, boolean>>({})

watch(() => props.items, () => {
  broken.value = {}
})

function mediaSource(media: MediaItem): string | undefined {
  return media.url || media.preview_image_url || undefined
}

function openMedia(media: MediaItem, event: Event) {
  const src = mediaSource(media)
  if (!src) return
  if (event.currentTarget instanceof HTMLElement) event.currentTarget.focus()
  emit("zoom", src)
}
</script>

<template>
  <div
    class="tweet-media media-tiles"
    :class="{
      'media-hover-zoom': hoverZoom,
      'media-tiles--ref': variant === 'ref',
    }"
  >
    <figure
      v-for="(media, index) in items"
      :key="index"
      class="media-tile"
      :data-testid="variant === 'ref' ? 'tweet-card-ref-media-item' : 'tweet-card-media-item'"
    >
      <img
        v-if="!broken[index] && mediaSource(media)"
        :src="mediaSource(media)"
        :width="media.width && media.height ? media.width : undefined"
        :height="media.width && media.height ? media.height : undefined"
        :alt="`媒体 ${index + 1}`"
        class="media-image"
        tabindex="0"
        role="button"
        :aria-label="`放大图片 ${index + 1}`"
        @click.stop="openMedia(media, $event)"
        @keydown.enter.stop.prevent="openMedia(media, $event)"
        @keydown.space.stop.prevent="openMedia(media, $event)"
        @error="broken[index] = true"
      >
      <span
        v-if="!broken[index] && media.type === 'video'"
        class="media-video-badge"
        data-testid="tweet-card-media-video-badge"
      >▶ 视频封面</span>
      <div
        v-if="broken[index] || !mediaSource(media)"
        class="media-broken"
        data-testid="tweet-card-media-broken"
      >⊘ 图片缺失</div>
    </figure>
  </div>
</template>

<style scoped>
.media-tiles {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 8px;
  margin-top: 12px;
}

.media-tile {
  position: relative;
  flex-shrink: 0;
  margin: 0;
  line-height: 0;
}

.media-image {
  display: block;
  width: auto;
  height: auto;
  max-width: var(--media-tile-w);
  max-height: var(--media-tile-h);
  border: 1px solid var(--border-light);
  border-radius: var(--el-border-radius-base);
  background: var(--bg-inset);
  cursor: zoom-in;
}

.media-tiles--ref .media-image {
  max-width: var(--media-tile-ref-w);
  max-height: var(--media-tile-ref-h);
}

.media-tiles--ref { margin-top: 10px; }

.media-hover-zoom .media-image {
  transition: transform var(--transition-base);
}

.media-hover-zoom .media-image:hover {
  transform: scale(1.02);
}

.media-image:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

.media-video-badge {
  position: absolute;
  bottom: 8px;
  left: 8px;
  padding: 2px 6px;
  border-radius: var(--el-border-radius-small);
  background: rgba(44, 36, 23, 0.72);
  color: white;
  font-family: var(--font-mono);
  font-size: var(--label-font-size);
  line-height: 1.5;
  pointer-events: none;
}

.media-broken {
  display: grid;
  place-items: center;
  width: var(--media-tile-w);
  height: var(--media-tile-h);
  border: 1px dashed var(--border-medium);
  border-radius: var(--el-border-radius-base);
  color: var(--text-secondary);
  font-family: var(--font-mono);
  font-size: var(--xs-font-size);
  line-height: 1.6;
}

.media-tiles--ref .media-broken {
  width: var(--media-tile-ref-w);
  height: var(--media-tile-ref-h);
}

@media (prefers-reduced-motion: reduce) {
  .media-image { transition: none !important; }
}
</style>
