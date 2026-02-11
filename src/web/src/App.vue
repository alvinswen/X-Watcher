<script setup lang="ts">
/** 应用根组件。 */
import { ref, onMounted } from "vue"
import { Setting } from "@element-plus/icons-vue"
import { getApiKey, setApiKey } from "@/api/client"
import { ElMessage } from "element-plus"

/** API Key 对话框是否可见 */
const apiKeyDialogVisible = ref(false)

/** API Key 输入值 */
const apiKeyInput = ref("")

/** 是否已配置 API Key */
const hasApiKey = ref(false)

/** 检查 API Key 状态 */
function checkApiKey() {
  hasApiKey.value = !!getApiKey()
}

/** 打开 API Key 设置对话框 */
function openApiKeyDialog() {
  apiKeyInput.value = getApiKey() || ""
  apiKeyDialogVisible.value = true
}

/** 保存 API Key */
function saveApiKey() {
  const key = apiKeyInput.value.trim()
  if (!key) {
    ElMessage.warning("请输入 API Key")
    return
  }
  setApiKey(key)
  hasApiKey.value = true
  apiKeyDialogVisible.value = false
  ElMessage.success("API Key 已保存")
}

onMounted(() => {
  checkApiKey()
})
</script>

<template>
  <div class="app">
    <header class="app-header">
      <h1 class="app-title">SeriousNewsAgent</h1>
      <div class="app-header-right">
        <nav class="app-nav">
          <RouterLink to="/tweets" class="nav-link">推文</RouterLink>
          <RouterLink to="/follows" class="nav-link">关注</RouterLink>
          <RouterLink to="/tasks" class="nav-link">任务</RouterLink>
        </nav>
        <el-button
          :icon="Setting"
          circle
          size="small"
          :type="hasApiKey ? 'default' : 'danger'"
          @click="openApiKeyDialog"
          :title="hasApiKey ? 'API Key 已配置' : '请配置 API Key'"
        />
      </div>
    </header>
    <main class="app-main">
      <RouterView />
    </main>

    <!-- API Key 设置对话框 -->
    <el-dialog v-model="apiKeyDialogVisible" title="API Key 设置" width="420px">
      <el-form>
        <el-form-item label="Admin API Key">
          <el-input
            v-model="apiKeyInput"
            placeholder="请输入管理员 API Key"
            show-password
          />
        </el-form-item>
        <el-text type="info" size="small">
          API Key 用于访问管理功能（关注管理、任务管理）。存储在浏览器本地。
        </el-text>
      </el-form>
      <template #footer>
        <el-button @click="apiKeyDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveApiKey">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.app {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.app-header {
  padding: 1rem 2rem;
  background-color: #f5f5f5;
  border-bottom: 1px solid #e0e0e0;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.app-title {
  margin: 0;
  font-size: 1.25rem;
  color: #333;
}

.app-header-right {
  display: flex;
  align-items: center;
  gap: 1.5rem;
}

.app-nav {
  display: flex;
  gap: 2rem;
}

.nav-link {
  color: #666;
  text-decoration: none;
  font-weight: 500;
  transition: color 0.2s;
}

.nav-link:hover,
.nav-link.router-link-active {
  color: #42b883;
}

.app-main {
  flex: 1;
  padding: 2rem;
}
</style>
