<template>
  <div class="my-follows-view">
    <div class="page-header">
      <div class="header-info">
        <p class="header-desc">
          管理您的 Twitter 关注列表。只能添加平台已收录的账号。
        </p>
      </div>
      <div class="header-actions">
        <el-input
          v-model="newUsername"
          placeholder="输入 Twitter 用户名"
          style="width: 240px"
          @keyup.enter="handleAdd"
        />
        <el-button type="primary" :loading="adding" @click="handleAdd">
          添加关注
        </el-button>
      </div>
    </div>

    <el-card>
      <el-skeleton v-if="loading" :rows="4" animated />
      <el-table v-else :data="follows" stripe>
        <el-table-column label="账号" min-width="150">
          <template #default="{ row }">
            @{{ row.username }}
          </template>
        </el-table-column>
        <el-table-column label="关注时间" width="200">
          <template #default="{ row }">
            {{ formatLocalizedDateTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button
              link
              type="danger"
              size="small"
              @click="handleRemove(row)"
            >
              取消关注
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from "vue"
import { ElMessage, ElMessageBox } from "element-plus"
import { preferencesApi } from "@/api"
import { formatLocalizedDateTime } from "@/utils/format"
import type { UserFollow } from "@/types"

const follows = ref<UserFollow[]>([])
const loading = ref(true)
const newUsername = ref("")
const adding = ref(false)

async function loadFollows() {
  loading.value = true
  try {
    follows.value = await preferencesApi.getFollows()
  } catch (error) {
    console.error("加载关注列表失败:", error)
  } finally {
    loading.value = false
  }
}

async function handleAdd() {
  const username = newUsername.value.trim().replace(/^@/, "")
  if (!username) {
    ElMessage.warning("请输入用户名")
    return
  }

  adding.value = true
  try {
    await preferencesApi.addFollow(username)
    ElMessage.success(`已添加关注 @${username}`)
    newUsername.value = ""
    await loadFollows()
  } catch (error: any) {
    const message = error?.response?.data?.detail || "添加关注失败"
    ElMessage.error(message)
  } finally {
    adding.value = false
  }
}

async function handleRemove(follow: UserFollow) {
  try {
    await ElMessageBox.confirm(
      `确定要取消关注 @${follow.username} 吗？`,
      "确认操作",
      { confirmButtonText: "确定", cancelButtonText: "取消", type: "warning" },
    )
  } catch {
    return
  }

  try {
    await preferencesApi.removeFollow(follow.username)
    ElMessage.success(`已取消关注 @${follow.username}`)
    await loadFollows()
  } catch (error: any) {
    const message = error?.response?.data?.detail || "取消关注失败"
    ElMessage.error(message)
  }
}

onMounted(() => {
  loadFollows()
})
</script>

<style scoped>
.my-follows-view {
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1.5rem;
}

.header-desc {
  margin: 0;
  font-size: 14px;
  color: var(--el-text-color-secondary);
}

.header-actions {
  display: flex;
  gap: 8px;
}
</style>
