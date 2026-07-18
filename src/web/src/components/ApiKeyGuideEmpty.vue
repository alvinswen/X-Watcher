<script setup lang="ts">
import { useAuthStore } from "@/stores/auth"

const authStore = useAuthStore()
</script>

<template>
  <el-empty
    :image-size="80"
    description="尚未配置管理员 API Key，配置后即可查看数据"
    data-testid="api-key-guide-empty"
  >
    <el-button
      type="primary"
      data-testid="api-key-guide-empty-action"
      @click="authStore.openDialog"
    >
      配置 API Key
    </el-button>
  </el-empty>
</template>
