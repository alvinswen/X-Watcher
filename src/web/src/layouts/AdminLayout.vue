<script setup lang="ts">
import { ref } from "vue"
import { useRoute } from "vue-router"
import {
  Odometer,
  Document,
  User,
  Monitor,
  Timer,
  UserFilled,
  Fold,
  Expand,
} from "@element-plus/icons-vue"
import { useAuthStore } from "@/stores/auth"
import { ElMessage } from "element-plus"

const route = useRoute()
const authStore = useAuthStore()

/** 侧边栏是否折叠 */
const isCollapsed = ref(false)

/** API Key 设置对话框是否可见 */
const apiKeyDialogVisible = ref(false)

/** API Key 输入值 */
const apiKeyInput = ref("")

/** 菜单项配置 */
const menuItems = [
  { index: "/dashboard", title: "仪表盘", icon: Odometer },
  { index: "/tweets", title: "推文管理", icon: Document },
  { index: "/follows", title: "关注管理", icon: User },
  { index: "/tasks", title: "任务监控", icon: Monitor },
  { index: "/scheduler", title: "调度管理", icon: Timer },
  { index: "/users", title: "用户管理", icon: UserFilled },
]

/** 打开 API Key 设置对话框 */
function openApiKeyDialog() {
  apiKeyInput.value = authStore.apiKey || ""
  apiKeyDialogVisible.value = true
}

/** 保存 API Key */
function saveApiKey() {
  const key = apiKeyInput.value.trim()
  if (!key) {
    ElMessage.warning("请输入 API Key")
    return
  }
  authStore.setApiKey(key)
  apiKeyDialogVisible.value = false
  ElMessage.success("API Key 已保存")
}

/** 清除 API Key */
function clearApiKey() {
  authStore.clearApiKey()
  apiKeyInput.value = ""
  apiKeyDialogVisible.value = false
  ElMessage.success("API Key 已清除")
}
</script>

<template>
  <el-container class="admin-layout">
    <!-- 侧边栏 -->
    <el-aside :width="isCollapsed ? '64px' : '220px'" class="admin-aside">
      <div class="aside-header">
        <span v-if="!isCollapsed" class="aside-title">X-watcher</span>
      </div>

      <el-menu
        :default-active="route.path"
        :collapse="isCollapsed"
        :collapse-transition="false"
        router
        class="aside-menu"
      >
        <el-menu-item
          v-for="item in menuItems"
          :key="item.index"
          :index="item.index"
        >
          <el-icon><component :is="item.icon" /></el-icon>
          <template #title>{{ item.title }}</template>
        </el-menu-item>
      </el-menu>

      <div class="aside-footer">
        <!-- API Key 状态指示器 -->
        <div class="api-key-status" @click="openApiKeyDialog">
          <span
            class="status-dot"
            :class="authStore.isAuthenticated ? 'status-active' : 'status-inactive'"
          />
          <span v-if="!isCollapsed" class="status-text">
            {{ authStore.isAuthenticated ? "API Key 已配置" : "未配置 API Key" }}
          </span>
        </div>

        <!-- 折叠/展开按钮 -->
        <el-icon class="collapse-btn" @click="isCollapsed = !isCollapsed">
          <Expand v-if="isCollapsed" />
          <Fold v-else />
        </el-icon>
      </div>
    </el-aside>

    <!-- 右侧内容区 -->
    <el-container>
      <el-header class="admin-header" height="50px">
        <span class="header-title">{{ route.meta.title }}</span>
      </el-header>
      <el-main class="admin-main">
        <slot />
      </el-main>
    </el-container>
  </el-container>

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
        API Key 用于访问管理功能（关注管理、任务管理等）。存储在浏览器本地。
      </el-text>
    </el-form>
    <template #footer>
      <el-button @click="clearApiKey" :disabled="!authStore.isAuthenticated">
        清除
      </el-button>
      <el-button @click="apiKeyDialogVisible = false">取消</el-button>
      <el-button type="primary" @click="saveApiKey">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.admin-layout {
  height: 100vh;
}

.admin-aside {
  background-color: #001529;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: width 0.2s;
}

.aside-header {
  height: 50px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.aside-title {
  color: #fff;
  font-size: 16px;
  font-weight: 600;
  white-space: nowrap;
}

.aside-menu {
  flex: 1;
  border-right: none;
  overflow-y: auto;
}

.aside-menu:not(.el-menu--collapse) {
  width: 220px;
}

.aside-footer {
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.api-key-status {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 4px;
  cursor: pointer;
  transition: background-color 0.2s;
}

.api-key-status:hover {
  background-color: rgba(255, 255, 255, 0.1);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-active {
  background-color: #67c23a;
}

.status-inactive {
  background-color: #909399;
}

.status-text {
  color: rgba(255, 255, 255, 0.65);
  font-size: 12px;
  white-space: nowrap;
}

.collapse-btn {
  color: rgba(255, 255, 255, 0.65);
  cursor: pointer;
  padding: 6px 8px;
  border-radius: 4px;
  font-size: 18px;
  align-self: center;
  transition: color 0.2s, background-color 0.2s;
}

.collapse-btn:hover {
  color: #fff;
  background-color: rgba(255, 255, 255, 0.1);
}

.admin-header {
  display: flex;
  align-items: center;
  border-bottom: 1px solid #e0e0e0;
  background-color: #fff;
  padding: 0 20px;
}

.header-title {
  font-size: 16px;
  font-weight: 500;
  color: #303133;
}

.admin-main {
  background-color: #f5f5f5;
  overflow-y: auto;
}
</style>
