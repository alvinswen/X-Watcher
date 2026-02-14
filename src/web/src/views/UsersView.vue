<template>
  <div class="users-view">
    <div class="page-header">
      <el-button type="primary" @click="showCreateDialog">创建用户</el-button>
    </div>

    <!-- 用户列表 -->
    <el-card>
      <el-skeleton v-if="loading" :rows="4" animated />
      <el-table v-else :data="users" stripe>
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
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
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
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from "vue"
import { ElMessage, ElMessageBox } from "element-plus"
import type { FormInstance, FormRules } from "element-plus"
import { usersApi } from "@/api"
import { formatLocalizedDateTime } from "@/utils/format"
import type { UserInfo } from "@/types"

/** 用户列表 */
const users = ref<UserInfo[]>([])

/** 加载状态 */
const loading = ref(true)

/** 创建对话框可见 */
const createDialogVisible = ref(false)

/** 创建中状态 */
const creating = ref(false)

/** 创建成功标记 */
const createSuccess = ref(false)

/** 创建表单引用 */
const createFormRef = ref<FormInstance>()

/** 创建表单数据 */
const createForm = reactive({
  name: "",
  email: "",
})

/** 创建表单校验规则 */
const createRules: FormRules = {
  name: [{ required: true, message: "请输入用户名", trigger: "blur" }],
  email: [
    { required: true, message: "请输入邮箱", trigger: "blur" },
    { type: "email", message: "请输入正确的邮箱格式", trigger: "blur" },
  ],
}

/** 创建成功后的凭据 */
const createdCredentials = reactive({
  temp_password: "",
  api_key: "",
})

/** 加载用户列表 */
async function loadUsers() {
  loading.value = true
  try {
    users.value = await usersApi.list()
  } catch (error) {
    console.error("加载用户列表失败:", error)
  } finally {
    loading.value = false
  }
}

/** 显示创建对话框 */
function showCreateDialog() {
  createSuccess.value = false
  createForm.name = ""
  createForm.email = ""
  createDialogVisible.value = true
}

/** 创建用户 */
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
  } catch (error: any) {
    const message = error?.response?.data?.detail || "创建用户失败"
    ElMessage.error(message)
  } finally {
    creating.value = false
  }
}

/** 确认凭据后关闭对话框 */
function handleCredentialConfirm() {
  createDialogVisible.value = false
  loadUsers()
}

/** 对话框关闭后重置状态 */
function handleCreateDialogClosed() {
  createSuccess.value = false
  createdCredentials.temp_password = ""
  createdCredentials.api_key = ""
}

/** 重置密码 */
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
  } catch (error: any) {
    const message = error?.response?.data?.detail || "重置密码失败"
    ElMessage.error(message)
  }
}

/** 复制到剪贴板 */
async function copyToClipboard(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success("已复制到剪贴板")
  } catch {
    ElMessage.error("复制失败，请手动复制")
  }
}

onMounted(() => {
  loadUsers()
})
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
