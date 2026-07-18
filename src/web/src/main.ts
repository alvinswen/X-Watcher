import { createApp } from "vue"
import { createPinia } from "pinia"
import { router } from "./router"
import ElementPlus from "element-plus"
import zhCn from "element-plus/es/locale/lang/zh-cn"
import "element-plus/dist/index.css"
import * as ElementPlusIconsVue from "@element-plus/icons-vue"
import "./style.css"
import App from "./App.vue"
import { useThemeStore } from "./stores/theme"

const app = createApp(App)

// 注册 Pinia 状态管理
const pinia = createPinia()
app.use(pinia)

// 初始化主题（尽早应用，避免闪烁）
useThemeStore().apply()

// 注册 Element Plus
app.use(ElementPlus, { locale: zhCn })

// 注册所有图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

// 注册路由
app.use(router)

app.mount("#app")
