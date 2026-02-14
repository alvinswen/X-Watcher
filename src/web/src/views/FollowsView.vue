<template>
  <div class="follows-view">
    <div class="page-header">
      <h1>抓取账号管理</h1>
      <el-button type="primary" :icon="Plus" @click="handleAdd">
        添加账号
      </el-button>
    </div>

    <!-- 加载状态 -->
    <el-skeleton v-if="loading" :rows="5" animated />

    <!-- 账号列表 -->
    <el-table v-else :data="follows" stripe border style="width: 100%">
      <el-table-column prop="username" label="用户名" width="150" />
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
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
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
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, reactive } from "vue"
import { Plus } from "@element-plus/icons-vue"
import { ElMessageBox, ElMessage, type FormInstance, type FormRules } from "element-plus"
import { followsApi } from "@/api"
import { formatLocalizedDateTime } from "@/utils/format"
import type { ScrapingFollow } from "@/types"

/** 抓取账号列表 */
const follows = ref<ScrapingFollow[]>([])

/** 加载状态 */
const loading = ref(false)

/** 提交状态 */
const submitting = ref(false)

/** 对话框显示状态 */
const dialogVisible = ref(false)

/** 是否为编辑模式 */
const isEditMode = ref(false)

/** 当前编辑的账号 */
const currentFollow = ref<ScrapingFollow | null>(null)

/** 表单引用 */
const formRef = ref<FormInstance>()

/** 表单数据 */
const formData = reactive({
  username: "",
  reason: "",
})

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
    follows.value = await followsApi.list()
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
  dialogVisible.value = true
}

/** 打开编辑对话框 */
function handleEdit(follow: ScrapingFollow) {
  isEditMode.value = true
  currentFollow.value = follow
  formData.username = follow.username
  formData.reason = follow.reason
  dialogVisible.value = true
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
</style>
