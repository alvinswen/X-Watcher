<template>
  <ApiKeyGuideEmpty v-if="needsApiKey" />
  <div v-else class="users-view" data-testid="users-view">
    <div class="page-header">
      <el-button
        type="primary"
        data-testid="users-create"
        @click="showCreateDialog"
      >
        创建用户
      </el-button>
    </div>

    <!-- 用户列表 -->
    <el-card data-testid="users-table-card">
      <el-skeleton v-if="loading" :rows="4" animated />
      <LoadErrorState v-else-if="loadError" :retry="retryLoadUsers" />
      <el-empty v-else-if="users.length === 0" description="暂无用户" />
      <el-table v-else :data="users" stripe row-key="id">
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="name" label="名称" min-width="120" />
        <el-table-column prop="email" label="邮箱" min-width="200" />
        <el-table-column label="角色" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.is_admin" type="danger" size="small">管理员</el-tag>
            <el-tag v-else type="info" size="small">普通用户</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="180">
          <template #default="{ row }">
            {{ formatLocalizedDateTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <el-button
              link
              type="primary"
              size="small"
              @click="showEditDialog(row)"
            >
              编辑
            </el-button>
            <el-button
              link
              type="primary"
              size="small"
              @click="handleResetPassword(row)"
            >
              重置密码
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 创建用户对话框 -->
    <el-dialog
      v-model="createDialogVisible"
      :title="createSuccess ? '创建成功' : '创建用户'"
      width="500px"
      :close-on-click-modal="false"
      @closed="handleCreateDialogClosed"
      data-testid="users-create-dialog"
    >
      <!-- 创建表单 -->
      <el-form
        v-if="!createSuccess"
        ref="createFormRef"
        :model="createForm"
        :rules="createRules"
        label-width="80px"
      >
        <el-form-item label="用户名" prop="name">
          <el-input v-model="createForm.name" placeholder="请输入用户名" />
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="createForm.email" placeholder="请输入邮箱" />
        </el-form-item>
      </el-form>

      <!-- 创建成功面板 -->
      <div v-else>
        <el-alert
          type="warning"
          title="此信息仅显示一次，请妥善保存"
          :closable="false"
          show-icon
          class="warning-alert"
        />
        <div class="credential-item">
          <label>临时密码</label>
          <el-input
            :model-value="createdCredentials.temp_password"
            readonly
          >
            <template #append>
              <el-button @click="copyToClipboard(createdCredentials.temp_password)">
                复制
              </el-button>
            </template>
          </el-input>
        </div>
        <div class="credential-item">
          <label>API Key</label>
          <el-input
            :model-value="createdCredentials.api_key"
            readonly
          >
            <template #append>
              <el-button @click="copyToClipboard(createdCredentials.api_key)">
                复制
              </el-button>
            </template>
          </el-input>
        </div>
      </div>

      <template #footer>
        <template v-if="!createSuccess">
          <el-button @click="createDialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="creating" @click="handleCreate">
            创建
          </el-button>
        </template>
        <template v-else>
          <el-button type="primary" @click="handleCredentialConfirm">确定</el-button>
        </template>
      </template>
    </el-dialog>

    <!-- 编辑用户对话框 -->
    <el-dialog
      v-model="editDialogVisible"
      title="编辑用户"
      width="500px"
      :close-on-click-modal="false"
      data-testid="users-edit-dialog"
    >
      <el-form
        ref="editFormRef"
        :model="editForm"
        :rules="editRules"
        label-width="80px"
      >
        <el-form-item label="名称" prop="name">
          <el-input v-model="editForm.name" placeholder="请输入用户名" />
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="editForm.email" placeholder="请输入邮箱" />
        </el-form-item>
        <el-form-item label="管理员">
          <el-switch v-model="editForm.is_admin" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="updating" @click="handleUpdate">
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from "vue"
import { ElMessage, ElMessageBox } from "element-plus"
import type { FormInstance, FormRules } from "element-plus"
import { usersApi } from "@/api"
import { ApiRequestError } from "@/api/client"
import ApiKeyGuideEmpty from "@/components/ApiKeyGuideEmpty.vue"
import LoadErrorState from "@/components/LoadErrorState.vue"
import { useApiKeyGuard } from "@/composables/useApiKeyGuard"
import { formatLocalizedDateTime } from "@/utils/format"
import type { UserInfo } from "@/types"

// ==================== 用户列表 ====================

const users = ref<UserInfo[]>([])
const loading = ref(true)
const loadError = ref(false)

async function loadUsers(preserveError = false) {
  loading.value = !preserveError
  if (!preserveError) {
    loadError.value = false
  }
  try {
    users.value = await usersApi.list()
    loadError.value = false
  } catch (error) {
    console.error("加载用户列表失败:", error)
    loadError.value = true
  } finally {
    loading.value = false
  }
}

function retryLoadUsers() {
  return loadUsers(true)
}

const { needsApiKey } = useApiKeyGuard(loadUsers)

// ==================== 创建用户 ====================

const createDialogVisible = ref(false)
const creating = ref(false)
const createSuccess = ref(false)
const createFormRef = ref<FormInstance>()

const createForm = reactive({
  name: "",
  email: "",
})

const createRules: FormRules = {
  name: [{ required: true, message: "请输入用户名", trigger: "blur" }],
  email: [
    { required: true, message: "请输入邮箱", trigger: "blur" },
    { type: "email", message: "请输入正确的邮箱格式", trigger: "blur" },
  ],
}

const createdCredentials = reactive({
  temp_password: "",
  api_key: "",
})

function showCreateDialog() {
  createSuccess.value = false
  createForm.name = ""
  createForm.email = ""
  createDialogVisible.value = true
}

async function handleCreate() {
  if (!createFormRef.value) return
  const valid = await createFormRef.value.validate().catch(() => false)
  if (!valid) return

  creating.value = true
  try {
    const response = await usersApi.create({
      name: createForm.name,
      email: createForm.email,
    })
    createdCredentials.temp_password = response.temp_password
    createdCredentials.api_key = response.api_key
    createSuccess.value = true
  } catch (error) {
    const message = error instanceof ApiRequestError
      ? error.detail || "创建用户失败"
      : "创建用户失败"
    ElMessage.error(message)
  } finally {
    creating.value = false
  }
}

function handleCredentialConfirm() {
  createDialogVisible.value = false
  loadUsers()
}

function handleCreateDialogClosed() {
  createSuccess.value = false
  createdCredentials.temp_password = ""
  createdCredentials.api_key = ""
}

// ==================== 编辑用户 ====================

const editDialogVisible = ref(false)
const updating = ref(false)
const editFormRef = ref<FormInstance>()
const editingUserId = ref<number | null>(null)

const editForm = reactive({
  name: "",
  email: "",
  is_admin: false,
})

const editRules: FormRules = {
  name: [{ required: true, message: "请输入用户名", trigger: "blur" }],
  email: [
    { required: true, message: "请输入邮箱", trigger: "blur" },
    { type: "email", message: "请输入正确的邮箱格式", trigger: "blur" },
  ],
}

function showEditDialog(user: UserInfo) {
  editingUserId.value = user.id
  editForm.name = user.name
  editForm.email = user.email
  editForm.is_admin = user.is_admin
  editDialogVisible.value = true
}

async function handleUpdate() {
  if (!editFormRef.value || editingUserId.value === null) return
  const valid = await editFormRef.value.validate().catch(() => false)
  if (!valid) return

  updating.value = true
  try {
    await usersApi.update(editingUserId.value, {
      name: editForm.name,
      email: editForm.email,
      is_admin: editForm.is_admin,
    })
    ElMessage.success("用户信息已更新")
    editDialogVisible.value = false
    await loadUsers()
  } catch (error) {
    const message = error instanceof ApiRequestError
      ? error.detail || "更新用户失败"
      : "更新用户失败"
    ElMessage.error(message)
  } finally {
    updating.value = false
  }
}

// ==================== 重置密码 ====================

async function handleResetPassword(user: UserInfo) {
  try {
    await ElMessageBox.confirm(
      `确定要重置用户「${user.name}」的密码吗？`,
      "重置密码",
      { confirmButtonText: "确定", cancelButtonText: "取消", type: "warning" },
    )
  } catch {
    return
  }

  try {
    const response = await usersApi.resetPassword(user.id)
    ElMessageBox.alert(
      `新临时密码: ${response.temp_password}`,
      "密码已重置",
      { confirmButtonText: "确定", type: "success" },
    )
  } catch (error) {
    const message = error instanceof ApiRequestError
      ? error.detail || "重置密码失败"
      : "重置密码失败"
    ElMessage.error(message)
  }
}

// ==================== 工具函数 ====================

async function copyToClipboard(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success("已复制到剪贴板")
  } catch {
    ElMessage.error("复制失败，请手动复制")
  }
}

</script>

<style scoped>
.users-view {
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 1.5rem;
}

.warning-alert {
  margin-bottom: 1rem;
}

.credential-item {
  margin-bottom: 1rem;
}

.credential-item label {
  display: block;
  font-size: 14px;
  color: var(--el-text-color-regular);
  margin-bottom: 4px;
}
</style>
