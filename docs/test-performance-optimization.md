# 测试性能优化报告

> 日期: 2026-02-14
> 优化前: 631s (10:31) | 优化后: 145s (2:25) | **降幅 77%**

## 问题背景

项目拥有 667 个测试用例，但单次完整运行耗时超过 10 分钟，严重影响开发迭代效率。通过 `pytest --durations=30` 定位到耗时集中在极少数测试的 teardown 阶段。

## 耗时分析

`--durations=30` 输出的 Top 10 如下：

| 耗时 | 阶段 | 测试文件 | 测试方法 |
|------|------|----------|----------|
| 88.2s | teardown | `test_tweets_routes_sync.py` | `test_list_tweets_default_params` |
| 75.1s | teardown | `test_tweets_routes_sync.py` | `test_list_tweets_with_pagination` |
| 55.1s | teardown | `test_tweets_routes_sync.py` | `test_list_tweets_invalid_page` |
| 53.4s | teardown | `test_tweets_routes_sync.py` | `test_list_tweets_filter_by_author` |
| 51.2s | teardown | `test_tweets_routes_sync.py` | `test_list_tweets_invalid_page_size` |
| 50.5s | teardown | `test_tweets_routes_sync.py` | `test_get_tweet_detail_success` |
| 50.1s | call | `test_integration.py` | `test_scheduler_job_skips_when_no_usernames` |
| 48.0s | teardown | `test_tweets_routes_sync.py` | `test_list_tweets_empty_author_filter` |
| 47.9s | teardown | `test_tweets_routes_sync.py` | `test_list_tweets_ordering` |
| 42.2s | teardown | `test_tweets_routes_sync.py` | `test_get_tweet_detail_not_found` |

**耗时分布汇总：**

| 区间 | 耗时 | 占比 | 根因 |
|------|------|------|------|
| `test_tweets_routes_sync.py` 9 个 teardown | ~560s | 89% | TestClient lifespan 中调度器 shutdown 阻塞 |
| `test_integration.py` 1 个测试 | ~50s | 8% | lifespan 中 asyncio.run() 在已有事件循环中阻塞 |
| `test_api_routes.py` batch 测试 | ~7s | 1% | 同上 |
| 其余 480+ 个测试 | ~14s | 2% | 正常 |

## 根因分析

### 1. BackgroundScheduler.shutdown(wait=True) 阻塞

`src/main.py` 的 lifespan 函数在 shutdown 阶段调用 `_scheduler.shutdown(wait=True)`，这是一个阻塞操作。

```python
# src/main.py lifespan()
if _scheduler:
    unregister_scheduler()
    _scheduler.shutdown(wait=True)  # 阻塞等待所有任务完成
```

`test_tweets_routes_sync.py` 中每个测试函数都创建一个 `TestClient(app)`，触发完整的 lifespan 启动和关闭周期：

- **启动**: 创建数据库表 + 初始化 BackgroundScheduler + 添加定时任务 + 启动调度器
- **关闭**: `_scheduler.shutdown(wait=True)` 阻塞等待

9 个测试 x ~60s/次 shutdown = **~560 秒**，占总耗时 89%。

### 2. asyncio.run() 事件循环冲突

`test_integration.py` 中 `TestClient(app)` 内部已有事件循环，但 lifespan 中 `_get_schedule_config_from_db()` 调用 `asyncio.run()` 尝试在已有循环中创建新循环，导致阻塞约 50 秒。

### 3. 默认覆盖率计算开销

`pyproject.toml` 中 `addopts` 默认包含 `--cov=src --cov-report=term-missing --cov-report=html`，每次 `pytest` 运行都执行覆盖率收集和 HTML 报告生成，增加约 10-20 秒开销。

## 优化方案

### 修改 1: `tests/api/test_tweets_routes_sync.py` — Fixture 提升为 module 级

**核心优化**，消除 ~560s 开销。

将 `_isolated_db`、`client`、`seed_test_tweets` 三个 fixture 的 scope 从 `function` 提升到 `module`，全模块共享一个 TestClient。同时在创建 TestClient 前设置 `SCRAPER_ENABLED=false`，阻止 lifespan 启动调度器。

```python
# 优化前: scope="function"，每个测试创建/销毁一次
@pytest.fixture(scope="function")
def client(_isolated_db) -> TestClient:
    with TestClient(app) as test_client:
        yield test_client

# 优化后: scope="module"，模块级共享 + 禁用调度器
@pytest.fixture(scope="module")
def client(_isolated_db) -> TestClient:
    os.environ["SCRAPER_ENABLED"] = "false"
    clear_settings_cache()
    with TestClient(app) as test_client:
        yield test_client
    clear_settings_cache()
```

**前提条件**: 该模块中的测试只读数据库，不会互相干扰，适合共享 fixture。

### 修改 2: `tests/scraper/test_integration.py` — 禁用调度器

消除 ~50s 开销。在 `integration_client` fixture 中设置 `SCRAPER_ENABLED=false` 并使用 `with TestClient(app) as c:` 确保正确的 context manager 用法。

```python
@pytest.fixture
def integration_client(test_settings):
    os.environ["SCRAPER_ENABLED"] = "false"
    clear_settings_cache()
    with patch("src.api.routes.admin.BackgroundTasks.add_task"):
        with TestClient(app) as c:
            yield c
    clear_settings_cache()
```

### 修改 3: `tests/unit/test_main.py` — 共享 TestClient + 更新断言

将 3 个使用 TestClient 的测试共享一个 module 级 fixture，并更新健康检查端点的断言（`/health` 现在返回包含 `components` 的结构化响应）。

```python
@pytest.fixture(scope="module")
def client():
    from src.main import app
    os.environ["SCRAPER_ENABLED"] = "false"
    clear_settings_cache()
    with TestClient(app) as c:
        yield c
    clear_settings_cache()
```

### 修改 4: `pyproject.toml` — 移除默认覆盖率

日常开发不需要覆盖率报告，移除 `addopts` 中的 `--cov` 相关配置。需要时手动运行：

```bash
# 日常开发
pytest tests/

# 需要覆盖率时
pytest tests/ --cov=src --cov-report=term-missing --cov-report=html
```

## 结果对比

| 指标 | 优化前 | 优化后 | 变化 |
|------|--------|--------|------|
| 总耗时 | 631s (10:31) | 145s (2:25) | **-77%** |
| 测试通过 | 665 passed | 667 passed | +2 (修复了 1 failed + 6 errors) |
| 测试失败 | 1 failed | 0 | 全部通过 |
| 测试错误 | 6 errors | 0 | 全部修复 |
| 跳过 | 2 skipped | 2 skipped | 不变 |

## 涉及文件

| 文件 | 改动类型 |
|------|----------|
| `tests/api/test_tweets_routes_sync.py` | fixture scope 提升 + 禁用调度器 |
| `tests/scraper/test_integration.py` | 禁用调度器 + context manager 修复 |
| `tests/unit/test_main.py` | 共享 TestClient + 更新健康检查断言 |
| `pyproject.toml` | 移除 addopts 中默认覆盖率配置 |

## 经验总结

1. **`pytest --durations=N` 是定位慢测试的第一步**。本次 89% 的耗时集中在一个文件的 teardown。
2. **TestClient lifespan 是隐藏成本**。每次创建 `TestClient(app)` 都触发完整的启动/关闭周期，包括调度器、数据库迁移等。
3. **测试中应禁用不相关的副作用**。`SCRAPER_ENABLED=false` 可以跳过调度器初始化，避免不必要的阻塞。
4. **Fixture scope 的选择很关键**。只读测试可以安全地共享 module/session 级 fixture，避免重复初始化。
5. **覆盖率收集适合 CI，不适合日常开发**。默认关闭、按需启用可以减少日常迭代的等待时间。
