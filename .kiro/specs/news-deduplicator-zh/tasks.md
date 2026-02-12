# Implementation Plan

## Task Format Template

Use whichever pattern fits the work breakdown:

### Major task only
- [ ] {{NUMBER}}. {{TASK_DESCRIPTION}}{{PARALLEL_MARK}}
  - {{DETAIL_ITEM_1}} *(Include details only when needed. If the task stands alone, omit bullet items.)*
  - _Requirements: {{REQUIREMENT_IDS}}_

### Major + Sub-task structure
- [ ] {{MAJOR_NUMBER}}. {{MAJOR_TASK_SUMMARY}}
- [ ] {{MAJOR_NUMBER}}.{{SUB_NUMBER}} {{SUB_TASK_DESCRIPTION}}{{SUB_PARALLEL_MARK}}
  - {{DETAIL_ITEM_1}}
  - {{DETAIL_ITEM_2}}
  - _Requirements: {{REQUIREMENT_IDS}}_ *(IDs only; do not add descriptions or parentheses.)*

> **Parallel marker**: Append ` (P)` only to tasks that can be executed in parallel. Omit the marker when running in `--sequential` mode.
>
> **Optional test coverage**: When a sub-task is deferrable test work tied to acceptance criteria, mark the checkbox as `- [ ]*` and explain the referenced requirements in the detail bullets.

---

## Tasks

### Phase 1: 数据层和领域模型

- [ ] 1. 创建去重相关的数据库迁移脚本
  - 创建 Alembic 迁移脚本添加 deduplication_groups 表
  - 在 tweets 表中添加 deduplication_group_id 外键字段
  - 创建必要的索引优化查询性能（部分索引、类型索引、时间索引）
  - 设置正确的外键约束和级联规则（SET NULL, ON DELETE CASCADE）
  - _Requirements: 3_

- [ ] 2. 实现去重相关的 ORM 模型
  - 创建 DeduplicationGroupOrm 实体类，映射到 deduplication_groups 表
  - 修改 TweetOrm 添加 deduplication_group_id 关联字段
  - 实现 to_domain 和 from_domain 方法用于模型转换
  - 添加 JSON 字段处理 tweet_ids 列表
  - _Requirements: 3_

### Phase 2: 领域检测器

- [ ] 3. 实现精确重复检测器
  - 创建 ExactDuplicateDetector 类，使用哈希表检测文本相同的推文
  - 实现转发关系检测（referenced_tweet_id + reference_type=retweeted）
  - 实现 DuplicateGroup 值对象模型（使用 Pydantic）
  - 确保主记录总是组中最早创建的推文（按 created_at 排序）
  - 添加单元测试验证 O(n) 时间复杂度和重复分组逻辑
  - _Requirements: 1_

- [ ] 4. (P) 实现相似内容检测器
  - 创建 SimilarityDetector 类，使用 scikit-learn 的 TF-IDF 和余弦相似度
  - 实现文本预处理函数（移除 URL、提及、多余空格，转小写）
  - 使用 TfidfVectorizer 将文本转换为 TF-IDF 向量
  - 使用 cosine_similarity 计算相似度矩阵
  - 实现阈值过滤（默认 0.85），返回超过阈值的相似组
  - 创建 SimilarGroup 值对象模型包含相似度分数
  - 预留嵌入模型接口（use_embedding_model 配置项）
  - 添加单元测试使用固定文本验证相似度计算
  - _Requirements: 2, 7_

### Phase 3: 配置和服务层

- [ ] 5. (P) 实现去重策略配置
  - 创建 DeduplicationConfig Pydantic 模型定义所有配置参数
  - 设置默认值（similarity_threshold=0.85, enable_exact_duplicate=True 等）
  - 添加配置验证逻辑（阈值范围检查、枚举值验证）
  - 实现从环境变量或数据库加载配置的逻辑
  - 添加测试验证默认值和配置覆盖
  - _Requirements: 5_

- [ ] 6. 实现去重结果仓库
  - 创建 DeduplicationRepository 类管理去重组的 CRUD 操作
  - 实现 save_groups 方法批量保存去重组
  - 实现 get_group 和 find_by_tweet 方法查询去重结果
  - 实现 delete_group 方法删除去重组（撤销操作）
  - 使用 AsyncSession 和事务确保数据一致性
  - 添加集成测试验证数据库操作和事务回滚
  - _Requirements: 3_

- [ ] 7. 实现去重编排服务
  - 创建 DeduplicationService 类协调整个去重流程
  - 实现分批处理逻辑（超过 1000 条时分批，避免内存溢出）
  - 实现增量去重策略：新推文与历史推文比较时限制时间窗口（最近 7 天）
  - 编排精确重复和相似度检测的执行顺序（精确优先）
  - 实现降级策略：相似度检测失败时仅使用精确重复结果
  - 生成去重统计报告（总推文数、重复组数、保留推文数）
  - 实现幂等性检查：已去重的推文跳过处理
  - 添加集成测试验证完整去重流程
  - _Requirements: 1, 2, 3, 4, 7_

### Phase 4: API 集成

- [ ] 8. 实现去重 API 端点
  - 创建 FastAPI 路由 /api/deduplicate/batch 接受推文 ID 列表
  - 创建 GET /api/deduplicate/groups/{group_id} 端点返回去重组详情
  - 创建 GET /api/deduplicate/tweets/{tweet_id} 端点查询推文去重状态
  - 创建 DELETE /api/deduplicate/groups/{group_id} 端点撤销去重
  - 使用 Pydantic 模型验证请求和响应
  - 实现错误处理（400, 404, 409, 500 状态码）
  - 添加 API 测试验证所有端点
  - _Requirements: 6_

- [ ] 9. 集成去重服务到抓取流程
  - 在 ScrapingService._save_tweets 方法后添加去重触发逻辑
  - 通过 FastAPI BackgroundTasks 异步执行去重
  - 实现自动触发：推文保存成功后自动调用去重服务
  - 处理去重失败场景（记录错误但不影响抓取结果）
  - 添加端到端测试验证抓取-去重完整流程
  - _Requirements: 6_

### Phase 5: 性能优化和测试

- [ ] 10. 实现性能优化
  - 为精确重复检测使用哈希表优化（O(n) 复杂度）
  - 为相似度检测使用矩阵运算优化（批量计算）
  - 实现预处理文本缓存避免重复计算
  - 添加性能测试验证 100 条推文 5 秒内完成
  - 添加性能测试验证 1000 条推文 30 秒内完成
  - 监控内存占用确保不超过 500MB（1000 条推文）
  - _Requirements: 7_

- [ ] 11. (P) 添加全面的测试覆盖
  - 补充 ExactDuplicateDetector 单元测试（边界情况）
  - 补充 SimilarityDetector 单元测试（边界情况、空输入）
  - 添加去重策略配置测试（验证、覆盖、默认值）
  - 添加并发去重测试（多个任务同时执行）
  - 添加分批处理测试（超过 1000 条推文）
  - 确保整体测试覆盖率达到 80% 以上
  - _Requirements: 1, 2, 4, 5, 7_

---

## Requirements Coverage

| Requirement | Tasks |
|-------------|-------|
| 1: 精确重复检测 | 3, 7, 11 |
| 2: 相似内容检测 | 4, 7, 11 |
| 3: 去重结果存储 | 1, 2, 6 |
| 4: 批量去重处理 | 7, 11 |
| 5: 去重策略配置 | 5, 11 |
| 6: API 集成 | 8, 9 |
| 7: 性能要求 | 4, 7, 10, 11 |

## Notes

- 任务 4 与任务 3 可以并行开发（独立的检测器）
- 任务 5 与任务 3/4 可以并行开发（独立的配置模块）
- 增量去重策略：使用时间窗口（最近 7 天）限制比较范围
- 与 ScrapingService 的集成点：在 _save_tweets 成功后触发
