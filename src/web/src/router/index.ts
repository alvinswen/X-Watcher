/** 路由配置。 */

import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router"

/** 路由配置 */
const routes: RouteRecordRaw[] = [
  {
    path: "/",
    name: "home",
    redirect: "/dashboard",
  },
  {
    path: "/dashboard",
    name: "dashboard",
    component: () => import("@/views/DashboardView.vue"),
    meta: {
      title: "仪表盘",
    },
  },
  {
    path: "/tweets",
    name: "tweets",
    component: () => import("@/views/TweetsView.vue"),
    meta: {
      title: "推文管理",
    },
  },
  {
    path: "/tweets/:id",
    name: "tweet-detail",
    component: () => import("@/views/TweetDetailView.vue"),
    meta: {
      title: "推文详情",
    },
  },
  {
    path: "/follows",
    name: "follows",
    component: () => import("@/views/FollowsView.vue"),
    meta: {
      title: "关注管理",
    },
  },
  {
    path: "/tasks",
    name: "tasks",
    component: () => import("@/views/TasksView.vue"),
    meta: {
      title: "任务监控",
    },
  },
  {
    path: "/scheduler",
    name: "scheduler",
    component: () => import("@/views/SchedulerView.vue"),
    meta: {
      title: "调度管理",
    },
  },
  {
    path: "/users",
    name: "users",
    component: () => import("@/views/UsersView.vue"),
    meta: {
      title: "用户管理",
    },
  },
]

/** 创建路由实例 */
export const router = createRouter({
  history: createWebHistory(),
  routes,
})

/** 路由守卫：更新页面标题 */
router.beforeEach((to) => {
  const title = to.meta.title as string | undefined
  if (title) {
    document.title = `${title} - X-watcher`
  } else {
    document.title = "X-watcher"
  }
})
