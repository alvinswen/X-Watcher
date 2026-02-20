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
        <el-button type="success" @click="batchAddDialogVisible = true">
          批量添加
        </el-button>
      </div>
    </div>

    <el-card>
      <!-- 批量操作栏 -->
      <div v-if="selectedRows.length > 0" class="batch-action-bar">
        <span class="batch-count">已选 {{ selectedRows.length }} 项</span>
        <el-button type="danger" size="small" @click="handleBatchRemove">
          批量取消关注
        </el-button>
      </div>

      <el-skeleton v-if="loading" :rows="4" animated />
      <el-table
        v-else
        :data="follows"
        stripe
        @selection-change="handleSelectionChange"
      >
        <el-table-column type="selection" width="50" />
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

    <!-- 批量添加对话框 -->
    <el-dialog
      v-model="batchAddDialogVisible"
      title="批量添加关注"
      width="520px"
      @closed="resetBatchAdd"
    >
      <template v-if="!batchAddResult">
        <el-form>
          <el-form-item label="用户名列表">
            <el-input
              v-model="batchAddInput"
              type="textarea"
              :rows="6"
              placeholder="每行一个用户名，或用逗号分隔。支持 @前缀（会自动去除）。"
            />
          </el-form-item>
        </el-form>
      </template>
      <template v-else>
        <el-result
          :icon="batchAddResult.failed_count === 0 ? 'success' : 'warning'"
          :title="`成功 ${batchAddResult.succeeded_count} 个，失败 ${batchAddResult.failed_count} 个`"
        >
          <template #extra>
            <div class="batch-result-detail">
              <div v-if="batchAddResult.succeeded.length > 0" class="result-section">
                <div class="result-label">成功：</div>
                <el-tag
                  v-for="name in batchAddResult.succeeded"
                  :key="name"
                  type="success"
                  size="small"
                  class="result-tag"
                >
                  @{{ name }}
                </el-tag>
              </div>
              <div v-if="batchAddResult.failed.length > 0" class="result-section">
                <div class="result-label">失败：</div>
                <div v-for="item in batchAddResult.failed" :key="item.username" class="fail-item">
                  <el-tag type="danger" size="small">@{{ item.username }}</el-tag>
                  <span class="fail-reason">{{ item.reason }}</span>
                </div>
              </div>
            </div>
          </template>
        </el-result>
      </template>
      <template #footer>
        <template v-if="!batchAddResult">
          <el-button @click="batchAddDialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="batchAdding" @click="handleBatchAdd">
            添加
          </el-button>
        </template>
        <template v-else>
          <el-button type="primary" @click="batchAddDialogVisible = false">
            关闭
          </el-button>
        </template>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from "vue"
import { ElMessage, ElMessageBox } from "element-plus"
import { preferencesApi } from "@/api"
import { formatLocalizedDateTime } from "@/utils/format"
import type { UserFollow, BatchFollowResponse } from "@/types"

const follows = ref<UserFollow[]>([])
const loading = ref(true)
const newUsername = ref("")
const adding = ref(false)

/** 多选 */
const selectedRows = ref<UserFollow[]>([])

/** 批量添加 */
const batchAddDialogVisible = ref(false)
const batchAddInput = ref("")
const batchAdding = ref(false)
const batchAddResult = ref<BatchFollowResponse | null>(null)

function handleSelectionChange(selection: UserFollow[]) {
  selectedRows.value = selection
}

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

/** 解析批量输入的用户名 */
function parseBatchUsernames(input: string): string[] {
  return input
    .split(/[\n,]+/)
    .map((s) => s.trim().replace(/^@/, ""))
    .filter((s) => s.length > 0)
}

/** 批量添加 */
async function handleBatchAdd() {
  const usernames = parseBatchUsernames(batchAddInput.value)
  if (usernames.length === 0) {
    ElMessage.warning("请输入至少一个用户名")
    return
  }

  batchAdding.value = true
  try {
    batchAddResult.value = await preferencesApi.batchAddFollows(usernames)
    await loadFollows()
  } catch (error: any) {
    const message = error?.response?.data?.detail || "批量添加失败"
    ElMessage.error(message)
  } finally {
    batchAdding.value = false
  }
}

/** 批量移除 */
async function handleBatchRemove() {
  const usernames = selectedRows.value.map((f) => f.username)
  if (usernames.length === 0) return

  try {
    await ElMessageBox.confirm(
      `确定要批量取消关注 ${usernames.length} 个账号吗？`,
      "确认操作",
      {
        confirmButtonText: "确定",
        cancelButtonText: "取消",
        type: "warning",
        confirmButtonClass: "el-button--danger",
      },
    )
  } catch {
    return
  }

  try {
    const result = await preferencesApi.batchRemoveFollows(usernames)
    ElMessage.success(`成功取消 ${result.succeeded_count} 个关注`)
    if (result.failed_count > 0) {
      ElMessage.warning(`${result.failed_count} 个取消失败`)
    }
    selectedRows.value = []
    await loadFollows()
  } catch (error: any) {
    const message = error?.response?.data?.detail || "批量取消关注失败"
    ElMessage.error(message)
  }
}

/** 重置批量添加对话框 */
function resetBatchAdd() {
  batchAddInput.value = ""
  batchAddResult.value = null
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

.batch-action-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  padding: 8px 12px;
  background: #fef0f0;
  border-radius: 4px;
}

.batch-count {
  font-size: 13px;
  color: var(--el-text-color-regular);
}

.batch-result-detail {
  text-align: left;
  max-height: 300px;
  overflow-y: auto;
}

.result-section {
  margin-bottom: 12px;
}

.result-label {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 6px;
  color: var(--el-text-color-primary);
}

.result-tag {
  margin: 2px 4px;
}

.fail-item {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.fail-reason {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
