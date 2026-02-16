# 研究与设计决策记录

## 概要
- **功能**: `tweet-browse-zh`
- **发现范围**: 扩展（Extension）— 在已有的六边形架构体系上新增独立模块
- **关键发现**:
  - Element Plus `el-calendar` 不提供 `panel-change` 事件，需通过 `watch` v-model 的月份变化检测月份切换
  - SQLite `DATE()` 函数返回字符串格式 `YYYY-MM-DD`，可直接用于 `GROUP BY`，SQLAlchemy 中使用 `func.date()`
  - FeedService 的 `tweets LEFT JOIN summaries` 查询模式可完全复用

## 研究日志

### Element Plus el-calendar 事件支持

- **上下文**: 需求 1.5 要求在用户切换日历月份时更新统计数据
- **来源**: [Element Plus Calendar 文档](https://element-plus.org/en-US/component/calendar)
- **发现**:
  - el-calendar 组件 **不提供任何事件**（无 Events/Emits 部分）
  - 仅有 Props（v-model, range, controller-type）、Slots（date-cell, header）和 Exposes（selectDate, pickDay）
  - v2.13.1 新增 `controller-type` 属性可设为 `"select"` 显示年/月下拉
  - `#date-cell` 插槽提供 `{ data }` 参数，其中 `data.day` 格式为 `YYYY-MM-DD`
- **影响**:
  - 使用 `watch` 监听 `selectedDate` 的月份变化来触发统计数据加载
  - 使用 `computed` 从 `selectedDate` 中提取年月，通过 `watch` 该 computed 值来检测变化

### SQLite DATE() 函数与 SQLAlchemy

- **上下文**: 后端 API 需要按日期分组统计推文数量
- **来源**: [SQLAlchemy DATE issue](https://github.com/sqlalchemy/sqlalchemy/issues/4922)
- **发现**:
  - SQLite 的 `DATE()` 函数返回字符串 `YYYY-MM-DD`
  - SQLAlchemy 中使用 `func.date(TweetOrm.created_at)` 调用 SQLite 原生 DATE 函数
  - `GROUP BY func.date(created_at)` 可正常工作
  - `created_at` 存储为 UTC 时间，DATE() 按 UTC 日期提取
- **影响**: 前端传入日期也应解释为 UTC 日期，V1 不做时区转换

### 作者 display_name 获取策略

- **上下文**: 需求 2.1 和 4.2 需要显示作者的 display_name
- **发现**:
  - 同一 `author_username` 在不同推文中可能有不同 `author_display_name`（用户改名）
  - SQLite 不支持 `DISTINCT ON`
  - 可用关联子查询获取每个作者最新推文的 display_name
- **影响**: 在 BrowseService 中使用关联子查询 `scalar_subquery` 获取最新 display_name

## 架构模式评估

| 方案 | 描述 | 优势 | 风险/限制 | 备注 |
|------|------|------|-----------|------|
| 方案 B: 新模块 | 新建 `src/browse/` 独立模块 | 职责清晰，独立可测试，符合六边形架构 | 更多文件 | 用户确认选择此方案 |

## 设计决策

### 决策 1: 新建独立 browse 模块

- **上下文**: 推文浏览与推文管理职责不同（消费 vs 操作）
- **备选方案**:
  1. 扩展现有 tweets API — 会使 tweets.py 臃肿
  2. 新建独立模块 — 清晰分离
- **选定方案**: 新建 `src/browse/` 模块
- **理由**: 与项目中 feed、deduplication、summarization 等模块保持一致的组织方式
- **权衡**: 多一组文件，但每个文件职责明确

### 决策 2: 月份切换检测使用 watch computed

- **上下文**: el-calendar 无 panel-change 事件
- **选定方案**: 定义 `currentYearMonth` computed 属性提取年月，watch 该值触发统计加载
- **理由**: 简洁可靠，不依赖 DOM 事件或组件内部实现

### 决策 3: 日期统一使用 UTC

- **上下文**: SQLite DATE() 按 UTC 提取日期
- **选定方案**: V1 统一使用 UTC 日期，前端日期参数传 `YYYY-MM-DD` 字符串
- **理由**: 简化实现，避免时区转换复杂度
- **权衡**: 东八区用户可能看到跨天推文归属不同日期（±1天偏差），可在 V2 优化

## 风险与缓解

- el-calendar 默认宽度较大（约 900px），侧边栏 320px 需通过 CSS 覆盖缩小 — 实现时测试并调整
- SQLite DATE() 返回字符串，需确保前端传入格式一致 — API 参数使用 `str` 类型并做正则校验
- 作者 display_name 子查询可能影响性能 — 作者列表通常 <50 条，性能可接受

## 参考

- [Element Plus Calendar](https://element-plus.org/en-US/component/calendar) — 组件 API 文档
- [SQLAlchemy func.date issue](https://github.com/sqlalchemy/sqlalchemy/issues/4922) — DATE 函数返回类型
