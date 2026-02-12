/** 路由配置。 */

import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router"

/** 路由配置 */
const routes: RouteRecordRaw[] = [
  {
    path: "/",
    name: "home",
    redirect: "/tweets",
  },
  {
    path: "/tweets",
    name: "tweets",
    component: () => import("@/views/TweetsView.vue"),
    meta: {
      title: "推文列表",
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
