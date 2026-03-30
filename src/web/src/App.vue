<script setup lang="ts">
/** 应用根组件。 */
import AdminLayout from "@/layouts/AdminLayout.vue"
</script>

<template>
  <AdminLayout>
    <RouterView v-slot="{ Component }">
      <Transition name="page-fade" mode="out-in">
        <component :is="Component" />
      </Transition>
    </RouterView>
  </AdminLayout>
</template>
