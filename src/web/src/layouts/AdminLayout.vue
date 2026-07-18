<script setup lang="ts">
import { provide, ref, watch } from "vue"
import { useRoute } from "vue-router"
import {
  Odometer,
  Document,
  Reading,
  User,
  UserFilled,
  Fold,
  Expand,
  FullScreen,
  Search,
  Refresh,
  Moon,
  Sunny,
  Collection,
} from "@element-plus/icons-vue"
import { useAuthStore } from "@/stores/auth"
import { useThemeStore } from "@/stores/theme"
import { ElMessage } from "element-plus"
import TwitterBalanceIndicator from "@/components/TwitterBalanceIndicator.vue"

const route = useRoute()
const authStore = useAuthStore()
const themeStore = useThemeStore()

/** 侧边栏是否折叠 */
const isCollapsed = ref(false)

/** 全屏模式 */
const isFullscreen = ref(false)
provide("isFullscreen", isFullscreen)

/** 长推文过滤 */
const longTweetFilterEnabled = ref(false)
const longTweetMinLength = ref(280)
provide("longTweetFilterEnabled", longTweetFilterEnabled)
provide("longTweetMinLength", longTweetMinLength)

function toggleFullscreen() {
  isFullscreen.value = !isFullscreen.value
}

/** API Key 输入值 */
const apiKeyInput = ref("")

/** 菜单项配置 */
const menuItems = [
  // —— 日常使用 ——
  { index: "/dashboard", title: "仪表盘", icon: Odometer },
  { index: "/browse", title: "推文浏览", icon: Reading },
  { index: "/search", title: "推文搜索", icon: Search },
  // —— 管理功能 ——
  { index: "/tweets", title: "推文管理", icon: Document },
  { index: "/follows", title: "关注管理", icon: User },
  { index: "/subjects", title: "议题管理", icon: Collection },
  { index: "/users", title: "用户管理", icon: UserFilled },
  { index: "/sync", title: "数据同步", icon: Refresh },
]

/** 打开 API Key 设置对话框 */
function openApiKeyDialog() {
  apiKeyInput.value = authStore.apiKey || ""
  authStore.openDialog()
}

watch(
  () => authStore.dialogVisible,
  (visible) => {
    if (visible) {
      apiKeyInput.value = authStore.apiKey || ""
    }
  },
)

/** 保存 API Key */
function saveApiKey() {
  const key = apiKeyInput.value.trim()
  if (!key) {
    ElMessage.warning("请输入 API Key")
    return
  }
  authStore.setApiKey(key)
  authStore.dialogVisible = false
  ElMessage.success("API Key 已保存")
}

/** 清除 API Key */
function clearApiKey() {
  authStore.clearApiKey()
  apiKeyInput.value = ""
  authStore.dialogVisible = false
  ElMessage.success("API Key 已清除")
}
</script>

<template>
  <el-container class="admin-layout">
    <!-- 侧边栏 -->
    <el-aside v-show="!isFullscreen" :width="isCollapsed ? '64px' : '220px'" class="admin-aside">
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

        <div class="aside-footer-actions">
          <!-- 主题切换按钮 -->
          <el-icon
            class="theme-toggle-btn"
            :title="themeStore.mode === 'light' ? '亮色模式' : themeStore.mode === 'dark' ? '暗色模式' : '跟随系统'"
            @click="themeStore.toggle()"
          >
            <Moon v-if="themeStore.isDark()" />
            <Sunny v-else />
          </el-icon>

          <!-- 折叠/展开按钮 -->
          <el-icon class="collapse-btn" @click="isCollapsed = !isCollapsed">
            <Expand v-if="isCollapsed" />
            <Fold v-else />
          </el-icon>
        </div>
      </div>
    </el-aside>

    <!-- 右侧内容区 -->
    <el-container>
      <el-header v-show="!isFullscreen" class="admin-header" height="50px">
        <span class="header-title">{{ route.meta.title }}</span>
        <span class="header-spacer"></span>
        <TwitterBalanceIndicator class="header-balance" />
        <template v-if="route.path === '/browse'">
          <el-switch
            v-model="longTweetFilterEnabled"
            active-text="长推"
            size="small"
            style="margin-right: 8px;"
          />
          <el-input-number
            v-if="longTweetFilterEnabled"
            v-model="longTweetMinLength"
            :min="1"
            :step="50"
            size="small"
            style="width: 130px; margin-right: 12px;"
            :prefix-icon="undefined"
            controls-position="right"
          >
            <template #prefix>≥</template>
          </el-input-number>
        </template>
        <el-button
          v-if="route.path === '/browse'"
          text
          :icon="FullScreen"
          @click="toggleFullscreen"
        >
          全屏
        </el-button>
      </el-header>
      <el-main class="admin-main">
        <slot />
      </el-main>
    </el-container>
  </el-container>

  <!-- API Key 设置对话框 -->
  <el-dialog v-model="authStore.dialogVisible" title="API Key 设置" width="420px">
    <el-form>
      <el-form-item label="管理员 API Key">
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
      <el-button @click="authStore.dialogVisible = false">取消</el-button>
      <el-button type="primary" @click="saveApiKey">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.admin-layout {
  height: 100vh;
}

.admin-aside {
  background-color: var(--bg-sidebar);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: width 0.35s cubic-bezier(0.4, 0, 0.2, 1);
}

.aside-header {
  height: 50px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.aside-title {
  color: var(--text-on-dark);
  font-size: 16px;
  font-weight: 600;
  white-space: nowrap;
  font-family: var(--font-reading);
  letter-spacing: 0.08em;
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
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.aside-footer-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
}

.api-key-status {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: background-color var(--transition-base);
}

.api-key-status:hover {
  background-color: var(--bg-sidebar-hover);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-active {
  background-color: var(--color-success);
}

.status-inactive {
  background-color: var(--text-tertiary);
}

.status-text {
  color: var(--text-on-dark-secondary);
  font-size: 12px;
  white-space: nowrap;
}

.theme-toggle-btn,
.collapse-btn {
  color: var(--text-on-dark-secondary);
  cursor: pointer;
  padding: 6px 8px;
  border-radius: 6px;
  font-size: 18px;
  transition: color var(--transition-base), background-color var(--transition-base);
}

.theme-toggle-btn:hover,
.collapse-btn:hover {
  color: var(--text-on-dark);
  background-color: var(--bg-sidebar-hover);
}

.admin-header {
  display: flex;
  align-items: center;
  border-bottom: 1px solid var(--border-light);
  background-color: var(--bg-card);
  padding: 0 20px;
}

.header-title {
  font-size: 16px;
  font-weight: 500;
  color: var(--text-primary);
  font-family: var(--font-reading);
}

.header-spacer {
  flex: 1;
}

.header-balance {
  margin-right: 12px;
}

.admin-main {
  background-color: var(--bg-page);
  overflow-y: auto;
}
</style>
