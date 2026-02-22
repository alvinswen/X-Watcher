<template>
  <div class="follows-view">
    <div class="page-header">
      <h1>抓取账号管理</h1>
      <div class="header-actions">
        <el-button
          :icon="Refresh"
          @click="handleSyncProfiles"
          :loading="syncing"
        >
          同步档案
        </el-button>
        <el-button type="primary" :icon="Plus" @click="handleAdd">
          添加账号
        </el-button>
      </div>
    </div>

    <!-- 加载状态 -->
    <el-skeleton v-if="loading" :rows="5" animated />

    <!-- 账号列表 -->
    <el-table v-else :data="follows" stripe border style="width: 100%">
      <el-table-column label="用户名" width="200">
        <template #default="{ row }">
          <div class="username-cell">
            <el-avatar
              v-if="getProfile(row.username)?.profile_picture"
              :src="getProfile(row.username)?.profile_picture!"
              :size="28"
              class="user-avatar"
            />
            <el-avatar v-else :size="28" class="user-avatar">
              {{ row.username.charAt(0).toUpperCase() }}
            </el-avatar>
            <span
              class="username-link"
              @click="handleShowProfile(row)"
            >
              @{{ row.username }}
            </span>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="platform_user_id" label="User ID" width="160">
        <template #default="{ row }">
          <span v-if="row.platform_user_id" class="user-id-text">
            {{ row.platform_user_id }}
          </span>
          <el-tag v-else type="warning" size="small">待补全</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="reason" label="添加理由" min-width="200" />
      <el-table-column prop="added_by" label="添加人" width="120" />
      <el-table-column prop="added_at" label="添加时间" width="180">
        <template #default="{ row }">
          {{ formatLocalizedDateTime(row.added_at) }}
        </template>
      </el-table-column>
      <el-table-column prop="is_active" label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
            {{ row.is_active ? "活跃" : "禁用" }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button
            link
            type="primary"
            size="small"
            @click="handleShowProfile(row)"
            :disabled="!getProfile(row.username)"
          >
            档案
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
            :type="row.is_active ? 'warning' : 'success'"
            size="small"
            @click="handleToggleActive(row)"
            :disabled="submitting"
          >
            {{ row.is_active ? "禁用" : "启用" }}
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

    <!-- 添加/编辑对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEditMode ? '编辑账号' : '添加账号'"
      width="500px"
    >
      <el-form
        ref="formRef"
        :model="formData"
        :rules="formRules"
        label-width="80px"
      >
        <el-form-item label="用户名" prop="username">
          <el-input
            v-model="formData.username"
            placeholder="请输入 Twitter 用户名（不含 @）"
            :disabled="isEditMode"
          />
        </el-form-item>
        <el-form-item label="添加理由" prop="reason">
          <el-input
            v-model="formData.reason"
            type="textarea"
            :rows="3"
            placeholder="请输入添加理由（至少 5 个字符）"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSubmit" :loading="submitting">
          {{ isEditMode ? "保存" : "添加" }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 用户档案抽屉 -->
    <el-drawer
      v-model="profileDrawerVisible"
      :title="selectedProfile ? `@${selectedProfile.username}` : '用户档案'"
      size="420px"
    >
      <div v-if="selectedProfile" class="profile-detail">
        <!-- 封面图 -->
        <div
          v-if="selectedProfile.cover_picture"
          class="profile-cover"
          :style="{ backgroundImage: `url(${selectedProfile.cover_picture})` }"
        />

        <!-- 头像和基本信息 -->
        <div class="profile-header">
          <el-avatar
            v-if="selectedProfile.profile_picture"
            :src="selectedProfile.profile_picture"
            :size="64"
          />
          <el-avatar v-else :size="64">
            {{ selectedProfile.username.charAt(0).toUpperCase() }}
          </el-avatar>
          <div class="profile-names">
            <div class="display-name">
              {{ selectedProfile.display_name || selectedProfile.username }}
              <el-tag
                v-if="selectedProfile.is_blue_verified"
                type="primary"
                size="small"
                class="verified-tag"
              >
                {{ selectedProfile.verified_type || "Blue" }}
              </el-tag>
            </div>
            <div class="handle">@{{ selectedProfile.username }}</div>
          </div>
        </div>

        <!-- 简介 -->
        <div v-if="selectedProfile.description" class="profile-bio">
          {{ selectedProfile.description }}
        </div>

        <!-- 位置 -->
        <div v-if="selectedProfile.location" class="profile-location">
          {{ selectedProfile.location }}
        </div>

        <!-- 统计数据 -->
        <div class="profile-stats">
          <div class="stat-item">
            <span class="stat-value">{{ formatNumber(selectedProfile.followers_count) }}</span>
            <span class="stat-label">粉丝</span>
          </div>
          <div class="stat-item">
            <span class="stat-value">{{ formatNumber(selectedProfile.following_count) }}</span>
            <span class="stat-label">关注</span>
          </div>
          <div class="stat-item">
            <span class="stat-value">{{ formatNumber(selectedProfile.statuses_count) }}</span>
            <span class="stat-label">推文</span>
          </div>
          <div class="stat-item">
            <span class="stat-value">{{ formatNumber(selectedProfile.media_count) }}</span>
            <span class="stat-label">媒体</span>
          </div>
        </div>

        <!-- 详细信息 -->
        <el-descriptions :column="1" border size="small" class="profile-details">
          <el-descriptions-item label="User ID">
            <span class="user-id-text">{{ selectedProfile.platform_user_id }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="账号创建">
            {{ selectedProfile.account_created_at || "-" }}
          </el-descriptions-item>
          <el-descriptions-item label="点赞数">
            {{ formatNumber(selectedProfile.favourites_count) }}
          </el-descriptions-item>
          <el-descriptions-item label="自动化账号">
            {{ selectedProfile.is_automated ? "是" : "否" }}
          </el-descriptions-item>
          <el-descriptions-item label="敏感标记">
            {{ selectedProfile.possibly_sensitive ? "是" : "否" }}
          </el-descriptions-item>
          <el-descriptions-item v-if="selectedProfile.unavailable" label="账号状态">
            <el-tag type="danger" size="small">
              不可用{{ selectedProfile.unavailable_reason ? `：${selectedProfile.unavailable_reason}` : "" }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="数据更新">
            {{ formatLocalizedDateTime(selectedProfile.fetched_at) }}
          </el-descriptions-item>
        </el-descriptions>
      </div>
      <el-empty v-else description="暂无档案数据" />
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, reactive, computed } from "vue"
import { Plus, Refresh } from "@element-plus/icons-vue"
import { ElMessageBox, ElMessage, type FormInstance, type FormRules } from "element-plus"
import { followsApi } from "@/api"
import { formatLocalizedDateTime } from "@/utils/format"
import type { ScrapingFollow, XUserProfile } from "@/types"

/** 抓取账号列表 */
const follows = ref<ScrapingFollow[]>([])

/** 用户档案列表 */
const profiles = ref<XUserProfile[]>([])

/** 加载状态 */
const loading = ref(false)

/** 提交状态 */
const submitting = ref(false)

/** 同步状态 */
const syncing = ref(false)

/** 对话框显示状态 */
const dialogVisible = ref(false)

/** 是否为编辑模式 */
const isEditMode = ref(false)

/** 当前编辑的账号 */
const currentFollow = ref<ScrapingFollow | null>(null)

/** 档案抽屉显示状态 */
const profileDrawerVisible = ref(false)

/** 选中的档案 */
const selectedProfile = ref<XUserProfile | null>(null)

/** 表单引用 */
const formRef = ref<FormInstance>()

/** 表单数据 */
const formData = reactive({
  username: "",
  reason: "",
  brief_intro: "",
})

/** 档案 Map（username -> profile） */
const profilesMap = computed(() => {
  const map = new Map<string, XUserProfile>()
  for (const p of profiles.value) {
    map.set(p.username.toLowerCase(), p)
  }
  return map
})

/** 根据用户名获取档案 */
function getProfile(username: string): XUserProfile | undefined {
  return profilesMap.value.get(username.toLowerCase())
}

/** 格式化数字 */
function formatNumber(value: number | null | undefined): string {
  if (value == null) return "-"
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`
  return value.toString()
}

/** 表单验证规则 */
const formRules: FormRules = {
  username: [
    { required: true, message: "请输入用户名", trigger: "blur" },
    {
      pattern: /^[a-zA-Z0-9_]{1,15}$/,
      message: "用户名只能包含字母、数字和下划线，1-15字符",
      trigger: "blur",
    },
  ],
  reason: [
    { required: true, message: "请输入添加理由", trigger: "blur" },
    { min: 5, message: "理由至少5个字符", trigger: "blur" },
  ],
}

/** 加载抓取账号列表 */
async function loadFollows() {
  loading.value = true
  try {
    const [followsData, profilesData] = await Promise.all([
      followsApi.list(),
      followsApi.listProfiles().catch(() => [] as XUserProfile[]),
    ])
    follows.value = followsData
    profiles.value = profilesData
  } catch (error) {
    console.error("加载抓取账号列表失败:", error)
  } finally {
    loading.value = false
  }
}

/** 打开添加对话框 */
function handleAdd() {
  isEditMode.value = false
  currentFollow.value = null
  formData.username = ""
  formData.reason = ""
  formData.brief_intro = ""
  dialogVisible.value = true
}

/** 打开编辑对话框 */
function handleEdit(follow: ScrapingFollow) {
  isEditMode.value = true
  currentFollow.value = follow
  formData.username = follow.username
  formData.reason = follow.reason
  formData.brief_intro = follow.brief_intro ?? ""
  dialogVisible.value = true
}

/** 显示用户档案 */
function handleShowProfile(follow: ScrapingFollow) {
  const profile = getProfile(follow.username)
  if (profile) {
    selectedProfile.value = profile
    profileDrawerVisible.value = true
  }
}

/** 同步档案 */
async function handleSyncProfiles() {
  syncing.value = true
  try {
    const result = await followsApi.syncProfiles()
    ElMessage.success(result.message)
    // 重新加载档案数据
    profiles.value = await followsApi.listProfiles().catch(() => [])
  } catch (error) {
    console.error("同步档案失败:", error)
  } finally {
    syncing.value = false
  }
}

/** 提交表单 */
async function handleSubmit() {
  if (!formRef.value) return

  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    if (isEditMode.value && currentFollow.value) {
      // 编辑
      await followsApi.update(currentFollow.value.username, {
        reason: formData.reason,
        brief_intro: formData.brief_intro || null,
      })
      ElMessage.success("账号更新成功")
    } else {
      // 添加
      await followsApi.add({
        username: formData.username,
        reason: formData.reason,
        added_by: "admin",
      })
      ElMessage.success("账号添加成功")
    }
    dialogVisible.value = false
    await loadFollows()
  } catch (error) {
    // 错误已被 API 拦截器处理
    console.error("操作失败:", error)
  } finally {
    submitting.value = false
  }
}

/** 切换活跃状态 */
async function handleToggleActive(follow: ScrapingFollow) {
  const action = follow.is_active ? "禁用" : "启用"
  try {
    await ElMessageBox.confirm(
      `确定要${action}账号 @${follow.username} 吗？`,
      "确认操作",
      {
        type: "warning",
      },
    )
    submitting.value = true
    await followsApi.toggleActive(follow.username, !follow.is_active)
    ElMessage.success(`账号已${action}`)
    await loadFollows()
  } catch (error) {
    if (error !== "cancel") {
      console.error("操作失败:", error)
    }
  } finally {
    submitting.value = false
  }
}

/** 删除账号 */
async function handleDelete(follow: ScrapingFollow) {
  try {
    await ElMessageBox.confirm(
      `确定要删除账号 @${follow.username} 吗？此操作不可恢复。`,
      "确认删除",
      {
        type: "warning",
        confirmButtonText: "删除",
        confirmButtonClass: "el-button--danger",
      },
    )
    submitting.value = true
    await followsApi.delete(follow.username)
    ElMessage.success("账号已删除")
    await loadFollows()
  } catch (error) {
    if (error !== "cancel") {
      console.error("删除失败:", error)
    }
  } finally {
    submitting.value = false
  }
}

/** 组件挂载时加载数据 */
onMounted(() => {
  loadFollows()
})
</script>

<style scoped>
.follows-view {
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

.header-actions {
  display: flex;
  gap: 0.5rem;
}

.user-id-text {
  font-family: monospace;
  font-size: 0.85em;
  color: #666;
}

.username-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.user-avatar {
  flex-shrink: 0;
}

.username-link {
  cursor: pointer;
  color: #409eff;
  font-weight: 500;
}

.username-link:hover {
  text-decoration: underline;
}

/* 档案抽屉样式 */
.profile-detail {
  padding: 0;
}

.profile-cover {
  width: 100%;
  height: 120px;
  background-size: cover;
  background-position: center;
  border-radius: 4px;
  margin-bottom: 1rem;
}

.profile-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 1rem;
}

.profile-names {
  flex: 1;
}

.display-name {
  font-size: 1.1rem;
  font-weight: 600;
  color: #333;
  display: flex;
  align-items: center;
  gap: 6px;
}

.verified-tag {
  font-size: 0.75rem;
}

.handle {
  color: #999;
  font-size: 0.9rem;
}

.profile-bio {
  color: #555;
  line-height: 1.5;
  margin-bottom: 0.75rem;
  white-space: pre-wrap;
}

.profile-location {
  color: #888;
  font-size: 0.85rem;
  margin-bottom: 1rem;
}

.profile-stats {
  display: flex;
  gap: 1.5rem;
  padding: 0.75rem 0;
  margin-bottom: 1rem;
  border-top: 1px solid #eee;
  border-bottom: 1px solid #eee;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.stat-value {
  font-weight: 600;
  font-size: 1rem;
  color: #333;
}

.stat-label {
  font-size: 0.75rem;
  color: #999;
}

.profile-details {
  margin-top: 0.5rem;
}
</style>
