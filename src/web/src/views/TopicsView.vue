<template>
  <div class="topics-view">
    <div class="page-header">
      <h1>主题管理</h1>
      <el-button type="primary" :icon="Plus" @click="handleAdd">
        创建主题
      </el-button>
    </div>

    <!-- 加载状态 -->
    <el-skeleton v-if="loading" :rows="5" animated />

    <!-- 主题列表 -->
    <el-table v-else :data="topics" stripe border style="width: 100%">
      <el-table-column prop="name" label="名称" width="200" />
      <el-table-column prop="description" label="描述" min-width="250" show-overflow-tooltip>
        <template #default="{ row }">
          {{ row.description || '-' }}
        </template>
      </el-table-column>
      <el-table-column prop="account_count" label="账号数量" width="120" align="center" />
      <el-table-column prop="created_at" label="创建时间" width="180">
        <template #default="{ row }">
          <el-tooltip :content="formatFullDateTime(row.created_at)" placement="top">
            <span>{{ formatRelativeTime(row.created_at) }}</span>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="280" fixed="right">
        <template #default="{ row }">
          <el-button
            link
            type="success"
            size="small"
            @click="handleViewSummary(row)"
            :disabled="submitting"
          >
            查看摘要
          </el-button>
          <el-button
            link
            type="primary"
            size="small"
            @click="handleManageAccounts(row)"
            :disabled="submitting"
          >
            管理账号
          </el-button>
          <el-button
            link
            type="primary"
            size="small"
            @click="handleEdit(row)"
            :disabled="submitting"
          >
            编辑
          </el-button>
          <el-button
            link
            type="danger"
            size="small"
            @click="handleDelete(row)"
            :disabled="submitting"
          >
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 创建/编辑对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEditMode ? '编辑主题' : '创建主题'"
      width="500px"
    >
      <el-form
        ref="formRef"
        :model="formData"
        :rules="formRules"
        label-width="80px"
      >
        <el-form-item label="名称" prop="name">
          <el-input
            v-model="formData.name"
            placeholder="请输入主题名称"
            maxlength="200"
            show-word-limit
          />
        </el-form-item>
        <el-form-item label="描述" prop="description">
          <el-input
            v-model="formData.description"
            type="textarea"
            :rows="3"
            placeholder="请输入主题描述（可选）"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSubmit" :loading="submitting">
          {{ isEditMode ? '保存' : '创建' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 摘要预览抽屉 -->
    <el-drawer
      v-model="summaryDrawerVisible"
      :title="`最新摘要 - ${summaryTopic?.name || ''}`"
      size="600px"
    >
      <el-skeleton v-if="summaryLoading" :rows="8" animated />
      <el-empty v-else-if="!summaryData" description="暂无已完成的摘要" />
      <div v-else class="summary-content">
        <el-descriptions :column="2" border size="small" class="summary-meta">
          <el-descriptions-item label="推文数">{{ summaryData.tweet_count }}</el-descriptions-item>
          <el-descriptions-item label="账号数">{{ summaryData.account_count }}</el-descriptions-item>
          <el-descriptions-item label="时间跨度">{{ summaryData.time_span_hours }} 小时</el-descriptions-item>
          <el-descriptions-item label="生成时间">{{ formatFullDateTime(summaryData.generated_at) }}</el-descriptions-item>
        </el-descriptions>
        <div class="summary-body">{{ summaryData.content }}</div>
      </div>
    </el-drawer>

    <!-- 账号管理抽屉 -->
    <el-drawer
      v-model="drawerVisible"
      :title="`管理账号 - ${currentTopic?.name || ''}`"
      size="480px"
    >
      <div class="drawer-content">
        <!-- 添加账号 -->
        <div class="add-account-section">
          <el-select
            v-model="selectedUsername"
            filterable
            placeholder="搜索并选择要添加的账号"
            style="flex: 1"
            :loading="followsLoading"
          >
            <el-option
              v-for="f in availableFollows"
              :key="f.username"
              :label="'@' + f.username"
              :value="f.username"
            />
          </el-select>
          <el-button
            type="primary"
            :disabled="!selectedUsername"
            :loading="accountSubmitting"
            @click="handleAddAccount"
          >
            添加
          </el-button>
        </div>

        <!-- 已关联账号列表 -->
        <div class="account-list">
          <div v-if="!topicAccounts.length" class="empty-text">
            暂无关联账号
          </div>
          <div
            v-for="account in topicAccounts"
            :key="account.id"
            class="account-item"
          >
            <span class="account-name">@{{ account.username }}</span>
            <span class="account-time">{{ formatRelativeTime(account.added_at) }}</span>
            <el-button
              link
              type="danger"
              size="small"
              @click="handleRemoveAccount(account)"
              :disabled="accountSubmitting"
            >
              移除
            </el-button>
          </div>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, reactive } from "vue"
import { Plus } from "@element-plus/icons-vue"
import { ElMessageBox, ElMessage, type FormInstance, type FormRules } from "element-plus"
import { topicsApi, followsApi } from "@/api"
import { formatRelativeTime, formatFullDateTime } from "@/utils/format"
import type { TopicListItem, TopicDetail, TopicAccount, LatestSummaryResponse } from "@/types/topic"
import type { ScrapingFollow } from "@/types"

/** 主题列表 */
const topics = ref<TopicListItem[]>([])

/** 加载状态 */
const loading = ref(false)

/** 提交状态 */
const submitting = ref(false)

/** 对话框显示状态 */
const dialogVisible = ref(false)

/** 是否为编辑模式 */
const isEditMode = ref(false)

/** 当前操作的主题 */
const currentTopic = ref<TopicListItem | null>(null)

/** 表单引用 */
const formRef = ref<FormInstance>()

/** 表单数据 */
const formData = reactive({
  name: "",
  description: "",
})

/** 表单验证规则 */
const formRules: FormRules = {
  name: [
    { required: true, message: "请输入主题名称", trigger: "blur" },
  ],
}

// ==================== 摘要预览状态 ====================

/** 摘要抽屉显示状态 */
const summaryDrawerVisible = ref(false)

/** 当前查看摘要的主题 */
const summaryTopic = ref<TopicListItem | null>(null)

/** 摘要数据 */
const summaryData = ref<LatestSummaryResponse | null>(null)

/** 摘要加载状态 */
const summaryLoading = ref(false)

// ==================== 账号管理状态 ====================

/** 抽屉显示状态 */
const drawerVisible = ref(false)

/** 当前主题的账号列表 */
const topicAccounts = ref<TopicAccount[]>([])

/** 抓取账号列表（用于添加选择） */
const scrapingFollows = ref<ScrapingFollow[]>([])

/** 抓取账号加载状态 */
const followsLoading = ref(false)

/** 选中要添加的用户名 */
const selectedUsername = ref("")

/** 账号操作提交状态 */
const accountSubmitting = ref(false)

/** 可选的抓取账号（排除已关联的） */
const availableFollows = computed(() => {
  const existingUsernames = new Set(topicAccounts.value.map((a) => a.username))
  return scrapingFollows.value.filter((f) => !existingUsernames.has(f.username))
})

// ==================== 主题 CRUD 方法 ====================

/** 加载主题列表 */
async function loadTopics() {
  loading.value = true
  try {
    topics.value = await topicsApi.list()
  } catch (error) {
    console.error("加载主题列表失败:", error)
  } finally {
    loading.value = false
  }
}

/** 打开创建对话框 */
function handleAdd() {
  isEditMode.value = false
  currentTopic.value = null
  formData.name = ""
  formData.description = ""
  dialogVisible.value = true
}

/** 打开编辑对话框 */
function handleEdit(topic: TopicListItem) {
  isEditMode.value = true
  currentTopic.value = topic
  formData.name = topic.name
  formData.description = topic.description || ""
  dialogVisible.value = true
}

/** 提交表单 */
async function handleSubmit() {
  if (!formRef.value) {
    ElMessage.warning("表单未初始化，请关闭对话框后重试")
    return
  }

  try {
    await formRef.value.validate()
  } catch {
    // validate() 验证失败时会 reject，Element Plus 已自动显示字段错误提示
    return
  }

  submitting.value = true
  try {
    if (isEditMode.value && currentTopic.value) {
      await topicsApi.update(currentTopic.value.id, {
        name: formData.name,
        description: formData.description || null,
      })
      ElMessage.success("主题更新成功")
    } else {
      await topicsApi.create({
        name: formData.name,
        description: formData.description || null,
      })
      ElMessage.success("主题创建成功")
    }
    dialogVisible.value = false
    await loadTopics()
  } catch (error) {
    // 错误已被 API 拦截器处理
    console.error("操作失败:", error)
  } finally {
    submitting.value = false
  }
}

/** 删除主题 */
async function handleDelete(topic: TopicListItem) {
  try {
    await ElMessageBox.confirm(
      `确定要删除主题「${topic.name}」吗？此操作不可恢复。`,
      "确认删除",
      {
        type: "warning",
        confirmButtonText: "删除",
        confirmButtonClass: "el-button--danger",
      },
    )
    submitting.value = true
    await topicsApi.delete(topic.id)
    ElMessage.success("主题已删除")
    await loadTopics()
  } catch (error) {
    if (error !== "cancel") {
      console.error("删除失败:", error)
    }
  } finally {
    submitting.value = false
  }
}

// ==================== 摘要预览方法 ====================

/** 查看最新摘要 */
async function handleViewSummary(topic: TopicListItem) {
  summaryTopic.value = topic
  summaryData.value = null
  summaryDrawerVisible.value = true
  summaryLoading.value = true
  try {
    summaryData.value = await topicsApi.getLatestSummary(topic.id)
  } catch (error: any) {
    if (error?.response?.status === 404) {
      summaryData.value = null
    } else {
      console.error("加载最新摘要失败:", error)
      summaryData.value = null
    }
  } finally {
    summaryLoading.value = false
  }
}

// ==================== 账号管理方法 ====================

/** 打开账号管理抽屉 */
async function handleManageAccounts(topic: TopicListItem) {
  currentTopic.value = topic
  selectedUsername.value = ""
  drawerVisible.value = true

  // 并行加载主题详情和抓取账号列表
  await Promise.all([loadTopicDetail(topic.id), loadScrapingFollows()])
}

/** 加载主题详情（获取账号列表） */
async function loadTopicDetail(topicId: number) {
  try {
    const detail: TopicDetail = await topicsApi.get(topicId)
    topicAccounts.value = detail.accounts
  } catch (error) {
    console.error("加载主题详情失败:", error)
  }
}

/** 加载抓取账号列表 */
async function loadScrapingFollows() {
  followsLoading.value = true
  try {
    scrapingFollows.value = await followsApi.list()
  } catch (error) {
    console.error("加载抓取账号列表失败:", error)
  } finally {
    followsLoading.value = false
  }
}

/** 添加账号 */
async function handleAddAccount() {
  if (!currentTopic.value || !selectedUsername.value) return

  accountSubmitting.value = true
  try {
    await topicsApi.addAccount(currentTopic.value.id, selectedUsername.value)
    ElMessage.success(`已添加 @${selectedUsername.value}`)
    selectedUsername.value = ""
    await loadTopicDetail(currentTopic.value.id)
    await loadTopics() // 刷新列表中的账号数量
  } catch (error) {
    console.error("添加账号失败:", error)
  } finally {
    accountSubmitting.value = false
  }
}

/** 移除账号 */
async function handleRemoveAccount(account: TopicAccount) {
  if (!currentTopic.value) return

  try {
    await ElMessageBox.confirm(
      `确定要移除账号 @${account.username} 吗？`,
      "确认移除",
      {
        type: "warning",
      },
    )
    accountSubmitting.value = true
    await topicsApi.removeAccount(currentTopic.value.id, account.username)
    ElMessage.success(`已移除 @${account.username}`)
    await loadTopicDetail(currentTopic.value.id)
    await loadTopics() // 刷新列表中的账号数量
  } catch (error) {
    if (error !== "cancel") {
      console.error("移除账号失败:", error)
    }
  } finally {
    accountSubmitting.value = false
  }
}

// ==================== 初始化 ====================

onMounted(() => {
  loadTopics()
})
</script>

<style scoped>
.topics-view {
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1.5rem;
}

.page-header h1 {
  margin: 0;
  font-size: 1.5rem;
  color: #333;
}

.drawer-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
}

.add-account-section {
  display: flex;
  gap: 8px;
  align-items: center;
}

.account-list {
  flex: 1;
  overflow-y: auto;
}

.account-item {
  display: flex;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.account-name {
  flex: 1;
  font-weight: 500;
}

.account-time {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-right: 12px;
}

.empty-text {
  text-align: center;
  color: var(--el-text-color-placeholder);
  padding: 40px 0;
}

.summary-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.summary-meta {
  margin-bottom: 8px;
}

.summary-body {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.8;
  font-size: 14px;
  color: var(--el-text-color-primary);
}
</style>
