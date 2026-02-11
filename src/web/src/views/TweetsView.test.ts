/** 推文列表组件测试。 */

import { describe, it, expect, beforeEach, vi } from "vitest"
import { mount, VueWrapper } from "@vue/test-utils"
import { createRouter, createMemoryHistory } from "vue-router"
import { ElSkeleton, ElEmpty, ElPagination } from "element-plus"
import TweetsView from "@/views/TweetsView.vue"

// Mock API
vi.mock("@/api", () => ({
  tweetsApi: {
    getList: vi.fn(),
  },
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

describe("TweetsView.vue", () => {
  let wrapper: VueWrapper

  const mockTweets = [
    {
      tweet_id: "tweet1",
      text: "First test tweet",
      author_username: "user1",
      author_display_name: "User One",
      created_at: "2024-01-01T00:00:00Z",
      has_summary: true,
      has_deduplication: false,
      media_count: 0,
    },
    {
      tweet_id: "tweet2",
      text: "Second test tweet",
      author_username: "user2",
      author_display_name: "User Two",
      created_at: "2024-01-02T00:00:00Z",
      has_summary: false,
      has_deduplication: true,
      media_count: 1,
    },
  ]

  beforeEach(async () => {
    // Reset mocks
    vi.clearAllMocks()

    // Mock API response
    const { tweetsApi } = await import("@/api")
    vi.mocked(tweetsApi.getList).mockResolvedValue({
      items: mockTweets,
      total: 2,
      page: 1,
      page_size: 20,
      total_pages: 1,
    })

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
        },
      },
    })

    // Wait for component to mount and load data
    await wrapper.vm.$nextTick()
  })

  afterEach(() => {
    if (wrapper) {
      wrapper.unmount()
    }
  })

  describe("组件挂载", () => {
    it("应该正确渲染组件", () => {
      expect(wrapper.exists()).toBe(true)
    })

    it("应该显示页面标题", () => {
      const title = wrapper.find("h1")
      expect(title.text()).toBe("推文列表")
    })

    it("应该在挂载时加载推文列表", async () => {
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
      // Set loading state
      await wrapper.setData({ loading: true })

      const skeleton = wrapper.findComponent(ElSkeleton)
      expect(skeleton.exists()).toBe(true)
    })

    it("空数据应该显示空状态", async () => {
      const { tweetsApi } = await import("@/api")
      vi.mocked(tweetsApi.getList).mockResolvedValue({
        items: [],
        total: 0,
        page: 1,
        page_size: 20,
        total_pages: 0,
      })

      await wrapper.setData({ loading: false, tweets: [] })

      const emptyState = wrapper.findComponent(ElEmpty)
      expect(emptyState.exists()).toBe(true)
    })
  })

  describe("推文列表渲染", () => {
    it("应该正确渲染推文列表", async () => {
      await wrapper.setData({
        loading: false,
        tweets: mockTweets,
        total: 2,
        totalPages: 1,
      })

      await wrapper.vm.$nextTick()

      const tweetCards = wrapper.findAll(".tweet-card")
      expect(tweetCards).toHaveLength(2)
    })

    it("应该显示推文作者信息", async () => {
      await wrapper.setData({
        loading: false,
        tweets: mockTweets,
      })

      await wrapper.vm.$nextTick()

      const authorNames = wrapper.findAll(".tweet-author")
      expect(authorNames[0].text()).toBe("User One")
      expect(authorNames[1].text()).toBe("User Two")
    })

    it("应该显示推文内容", async () => {
      await wrapper.setData({
        loading: false,
        tweets: mockTweets,
      })

      await wrapper.vm.$nextTick()

      const contents = wrapper.findAll(".tweet-content")
      expect(contents[0].text()).toBe("First test tweet")
      expect(contents[1].text()).toBe("Second test tweet")
    })

    it("应该显示摘要状态标签", async () => {
      await wrapper.setData({
        loading: false,
        tweets: mockTweets,
      })

      await wrapper.vm.$nextTick()

      const tags = wrapper.findAll(".tweet-footer .el-tag")
      expect(tags.length).toBeGreaterThan(0)
    })
  })

  describe("分页功能", () => {
    it("应该显示分页组件", async () => {
      await wrapper.setData({
        loading: false,
        tweets: mockTweets,
        totalPages: 2,
      })

      await wrapper.vm.$nextTick()

      const pagination = wrapper.findComponent(ElPagination)
      expect(pagination.exists()).toBe(true)
    })

    it("应该能够切换页码", async () => {
      const { tweetsApi } = await import("@/api")

      await wrapper.setData({
        loading: false,
        tweets: mockTweets,
        totalPages: 2,
      })

      await wrapper.vm.handlePageChange(2)

      expect(tweetsApi.getList).toHaveBeenCalledWith({
        page: 2,
        page_size: 20,
        author: undefined,
      })
    })

    it("应该能够调整每页数量", async () => {
      const { tweetsApi } = await import("@/api")

      await wrapper.setData({
        loading: false,
        tweets: mockTweets,
      })

      await wrapper.vm.handleSizeChange(50)

      expect(tweetsApi.getList).toHaveBeenCalledWith({
        page: 1,
        page_size: 50,
        author: undefined,
      })
    })
  })

  describe("筛选功能", () => {
    it("应该能够按作者筛选", async () => {
      const { tweetsApi } = await import("@/api")

      await wrapper.setData({
        filterAuthor: "user1",
      })

      await wrapper.vm.handleFilterChange()

      expect(tweetsApi.getList).toHaveBeenCalledWith({
        page: 1,
        page_size: 20,
        author: "user1",
      })
    })

    it("清空筛选应该重置为第一页", async () => {
      await wrapper.setData({
        currentPage: 2,
      })

      await wrapper.vm.handleFilterChange()

      expect(wrapper.vm.currentPage).toBe(1)
    })
  })

  describe("刷新功能", () => {
    it("刷新按钮应该重新加载数据", async () => {
      const { tweetsApi } = await import("@/api")

      await wrapper.vm.handleRefresh()

      expect(tweetsApi.getList).toHaveBeenCalled()
      expect(wrapper.vm.currentPage).toBe(1)
    })
  })

  describe("导航功能", () => {
    it("点击推文卡片应该跳转到详情页", async () => {
      const pushSpy = vi.spyOn(router, "push")

      await wrapper.setData({
        loading: false,
        tweets: mockTweets,
      })

      await wrapper.vm.handleTweetClick("tweet1")

      expect(pushSpy).toHaveBeenCalledWith("/tweets/tweet1")
    })
  })
})
