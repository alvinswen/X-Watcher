/** 推文列表组件测试。 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { mount, flushPromises, VueWrapper } from "@vue/test-utils"
import { createRouter, createMemoryHistory } from "vue-router"
import { ElSkeleton, ElEmpty, ElPagination } from "element-plus"
import TweetsView from "@/views/TweetsView.vue"
import type { TweetListItem } from "@/types"

// Mock API
vi.mock("@/api", () => ({
  tweetsApi: {
    getList: vi.fn(),
  },
  summariesApi: {
    batchSummarize: vi.fn(),
    getTaskStatus: vi.fn(),
  },
  dedupApi: {
    batchDeduplicate: vi.fn(),
    getTaskStatus: vi.fn(),
  },
}))

// Mock polling service
vi.mock("@/services/polling", () => ({
  taskPollingService: {
    startPolling: vi.fn(),
    stopAll: vi.fn(),
  },
}))

// Mock format util
vi.mock("@/utils/format", () => ({
  formatRelativeTime: vi.fn((date: string) => date),
}))

// Mock router
const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: "/", component: { template: "<div>Home</div>" } },
    { path: "/tweets", component: TweetsView },
    { path: "/tweets/:id", component: { template: "<div>Detail</div>" } },
  ],
})

const mockTweets: TweetListItem[] = [
  {
    tweet_id: "tweet1",
    text: "First test tweet",
    author_username: "user1",
    author_display_name: "User One",
    created_at: "2024-01-01T00:00:00+00:00",
    db_created_at: "2024-01-01T00:00:01+00:00",
    reference_type: null,
    referenced_tweet_id: null,
    has_summary: true,
    has_deduplication: false,
    media_count: 0,
  },
  {
    tweet_id: "tweet2",
    text: "Second test tweet",
    author_username: "user2",
    author_display_name: "User Two",
    created_at: "2024-01-02T00:00:00+00:00",
    db_created_at: "2024-01-02T00:00:01+00:00",
    reference_type: null,
    referenced_tweet_id: null,
    has_summary: false,
    has_deduplication: true,
    media_count: 1,
  },
]

const mockResponse = {
  items: mockTweets,
  total: 2,
  page: 1,
  page_size: 20,
  total_pages: 1,
}

/** 创建并挂载组件，等待 API 数据加载完成 */
async function mountAndWait(apiResponse = mockResponse): Promise<VueWrapper> {
  const { tweetsApi } = await import("@/api")
  vi.mocked(tweetsApi.getList).mockResolvedValue(apiResponse)

  const wrapper = mount(TweetsView, {
    global: {
      plugins: [router],
      stubs: {
        ElSkeleton: true,
        ElEmpty: true,
        ElPagination: true,
        ElButton: true,
        ElInput: true,
        ElTag: true,
        ElCheckbox: true,
        ElTooltip: true,
      },
    },
  })

  // 等待 onMounted 中的异步 API 调用完成
  await flushPromises()

  return wrapper
}

describe("TweetsView.vue", () => {
  let wrapper: VueWrapper

  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    if (wrapper) {
      wrapper.unmount()
    }
  })

  describe("组件挂载", () => {
    it("应该正确渲染组件", async () => {
      wrapper = await mountAndWait()
      expect(wrapper.exists()).toBe(true)
    })

    it("应该显示页面标题", async () => {
      wrapper = await mountAndWait()
      const title = wrapper.find("h1")
      expect(title.text()).toBe("推文列表")
    })

    it("应该在挂载时加载推文列表", async () => {
      wrapper = await mountAndWait()
      const { tweetsApi } = await import("@/api")
      expect(tweetsApi.getList).toHaveBeenCalledWith({
        page: 1,
        page_size: 20,
        author: undefined,
      })
    })
  })

  describe("加载状态", () => {
    it("加载中应该显示骨架屏", async () => {
      // Mock API 返回一个永不 resolve 的 Promise，使组件保持 loading 状态
      const { tweetsApi } = await import("@/api")
      vi.mocked(tweetsApi.getList).mockReturnValue(new Promise(() => {}))

      wrapper = mount(TweetsView, {
        global: {
          plugins: [router],
          stubs: {
            ElSkeleton: true,
            ElEmpty: true,
            ElPagination: true,
            ElButton: true,
            ElInput: true,
            ElTag: true,
            ElCheckbox: true,
            ElTooltip: true,
          },
        },
      })

      // 此时 API 还没返回，loading 应该为 true，tweets 为空
      await wrapper.vm.$nextTick()

      const skeleton = wrapper.findComponent(ElSkeleton)
      expect(skeleton.exists()).toBe(true)
    })

    it("空数据应该显示空状态", async () => {
      wrapper = await mountAndWait({
        items: [],
        total: 0,
        page: 1,
        page_size: 20,
        total_pages: 0,
      })

      const emptyState = wrapper.findComponent(ElEmpty)
      expect(emptyState.exists()).toBe(true)
    })
  })

  describe("推文列表渲染", () => {
    it("应该正确渲染推文列表", async () => {
      wrapper = await mountAndWait()

      const tweetCards = wrapper.findAll(".tweet-card")
      expect(tweetCards).toHaveLength(2)
    })

    it("应该显示推文作者信息", async () => {
      wrapper = await mountAndWait()

      const authorNames = wrapper.findAll(".tweet-author")
      expect(authorNames[0].text()).toBe("User One")
      expect(authorNames[1].text()).toBe("User Two")
    })

    it("应该显示推文内容", async () => {
      wrapper = await mountAndWait()

      const contents = wrapper.findAll(".tweet-content")
      expect(contents[0].text()).toBe("First test tweet")
      expect(contents[1].text()).toBe("Second test tweet")
    })

    it("应该显示摘要状态标签", async () => {
      wrapper = await mountAndWait()

      // 使用 stubbed 的 el-tag，查找 stub 元素
      const footers = wrapper.findAll(".tweet-footer")
      expect(footers.length).toBe(2)
      // 第一条推文有 has_summary=true，应该至少有一个 tag
      const firstFooterTags = footers[0].findAll("el-tag-stub")
      expect(firstFooterTags.length).toBeGreaterThan(0)
    })
  })

  describe("分页功能", () => {
    it("应该在多页时显示分页组件", async () => {
      wrapper = await mountAndWait({
        items: mockTweets,
        total: 40,
        page: 1,
        page_size: 20,
        total_pages: 2,
      })

      const pagination = wrapper.findComponent(ElPagination)
      expect(pagination.exists()).toBe(true)
    })

    it("应该能够切换页码", async () => {
      wrapper = await mountAndWait()
      const { tweetsApi } = await import("@/api")

      // 清除 onMounted 的调用记录
      vi.mocked(tweetsApi.getList).mockClear()
      vi.mocked(tweetsApi.getList).mockResolvedValue(mockResponse)

      // 调用 handlePageChange 方法
      await (wrapper.vm as any).handlePageChange(2)
      await flushPromises()

      expect(tweetsApi.getList).toHaveBeenCalledWith({
        page: 2,
        page_size: 20,
        author: undefined,
      })
    })

    it("应该能够调整每页数量", async () => {
      wrapper = await mountAndWait()
      const { tweetsApi } = await import("@/api")

      vi.mocked(tweetsApi.getList).mockClear()
      vi.mocked(tweetsApi.getList).mockResolvedValue(mockResponse)

      await (wrapper.vm as any).handleSizeChange(50)
      await flushPromises()

      expect(tweetsApi.getList).toHaveBeenCalledWith({
        page: 1,
        page_size: 50,
        author: undefined,
      })
    })
  })

  describe("筛选功能", () => {
    it("应该能够按作者筛选", async () => {
      wrapper = await mountAndWait()
      const { tweetsApi } = await import("@/api")

      // 通过 vm 设置 filterAuthor（script setup 中的 ref）
      ;(wrapper.vm as any).filterAuthor = "user1"

      vi.mocked(tweetsApi.getList).mockClear()
      vi.mocked(tweetsApi.getList).mockResolvedValue(mockResponse)

      await (wrapper.vm as any).handleFilterChange()
      await flushPromises()

      expect(tweetsApi.getList).toHaveBeenCalledWith({
        page: 1,
        page_size: 20,
        author: "user1",
      })
    })

    it("清空筛选应该重置为第一页", async () => {
      wrapper = await mountAndWait()

      // 模拟用户在第 2 页
      ;(wrapper.vm as any).currentPage = 2

      await (wrapper.vm as any).handleFilterChange()
      await flushPromises()

      expect((wrapper.vm as any).currentPage).toBe(1)
    })
  })

  describe("刷新功能", () => {
    it("刷新按钮应该重新加载数据", async () => {
      wrapper = await mountAndWait()
      const { tweetsApi } = await import("@/api")

      vi.mocked(tweetsApi.getList).mockClear()
      vi.mocked(tweetsApi.getList).mockResolvedValue(mockResponse)

      await (wrapper.vm as any).handleRefresh()
      await flushPromises()

      expect(tweetsApi.getList).toHaveBeenCalled()
      expect((wrapper.vm as any).currentPage).toBe(1)
    })
  })

  describe("导航功能", () => {
    it("点击推文卡片应该跳转到详情页", async () => {
      wrapper = await mountAndWait()
      const pushSpy = vi.spyOn(router, "push")

      await (wrapper.vm as any).handleTweetClick("tweet1")

      expect(pushSpy).toHaveBeenCalledWith("/tweets/tweet1")
    })
  })
})
