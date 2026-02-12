# X-watcher 用户手册

本手册将帮助你从零开始启动 X-watcher 智能信息监控系统，并通过 Web 前端验证各项功能。

## 目录

1. [环境准备](#环境准备)
2. [配置说明](#配置说明)
3. [启动项目](#启动项目)
4. [前端功能验证](#前端功能验证)
5. [API 端点总览](#api-端点总览)
6. [典型工作流程](#典型工作流程)
7. [常见问题](#常见问题)
8. [监控和调试](#监控和调试)

---

## 环境准备

### 系统要求

- **Python** >= 3.11
- **Node.js** >= 18（用于前端开发服务器）
- **npm** >= 9

### 安装后端依赖

```bash
cd X-watcher

# 创建虚拟环境（推荐）
python -m venv .venv

# 激活虚拟环境
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 安装项目依赖
pip install -e .

# 安装开发依赖（可选，用于测试）
pip install -e ".[dev]"
```

### 安装前端依赖

```bash
cd src/web
npm install
```

---

## 配置说明

### 创建 `.env` 文件

在项目根目录下复制并编辑环境变量文件：

```bash
cp .env.example .env
```

### 必填配置

| 配置项 | 说明 | 获取方式 |
|--------|------|----------|
| `MINIMAX_API_KEY` | MiniMax AI 摘要 API 密钥 | 访问 https://api.minimaxi.com/ 注册获取 |
| `TWITTER_API_KEY` | TwitterAPI.io 的 API 密钥 | 访问 https://twitterapi.io/ 注册获取 |

### 可选配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `DATABASE_URL` | `sqlite:///./news_agent.db` | 数据库连接字符串 |
| `ADMIN_API_KEY` | 无 | 管理员 API 认证密钥，用于保护管理接口 |
| `SCRAPER_ENABLED` | `true` | 是否启用定时抓取 |
| `SCRAPER_INTERVAL` | `3600` | 定时抓取间隔（秒） |
| `SCRAPER_USERNAMES` | 无 | 默认抓取的用户名列表，逗号分隔 |
| `SCRAPER_LIMIT` | `100` | 每次抓取的推文数量上限 |
| `LOG_LEVEL` | `INFO` | 日志级别（DEBUG/INFO/WARNING/ERROR） |
| `PROMETHEUS_ENABLED` | `true` | 是否启用 Prometheus 监控 |
| `AUTO_SUMMARIZATION_ENABLED` | `true` | 抓取后是否自动生成 AI 摘要 |
| `AUTO_SUMMARIZATION_BATCH_SIZE` | `50` | 自动摘要批处理大小 |

### `.env` 文件示例

```bash
# === 必填 ===
MINIMAX_API_KEY=你的_minimax_api_key
MINIMAX_BASE_URL=https://api.minimaxi.com
TWITTER_API_KEY=你的_twitterapi_io_key
TWITTER_BEARER_TOKEN=dummy_placeholder
TWITTER_BASE_URL=https://api.twitterapi.io/twitter

# === 管理员 ===
ADMIN_API_KEY=my_secret_admin_key

# === 抓取器 ===
SCRAPER_ENABLED=true
SCRAPER_INTERVAL=3600
SCRAPER_USERNAMES=elonmusk,OpenAI,nvidia
SCRAPER_LIMIT=100

# === 数据库 ===
DATABASE_URL=sqlite:///./news_agent.db

# === 日志 ===
LOG_LEVEL=INFO

# === 自动摘要 ===
AUTO_SUMMARIZATION_ENABLED=true
AUTO_SUMMARIZATION_BATCH_SIZE=50
```

---

## 启动项目

项目由**后端服务**（FastAPI）和**前端开发服务器**（Vite）两部分组成。开发时需要同时启动。

### 第一步：初始化数据库

```bash
# 运行种子脚本，创建默认管理员账户（需以模块方式运行）
python -m scripts.seed_admin
```

### 第二步：启动后端服务

```bash
# 方式一：直接运行
python -m src.main

# 方式二：使用 uvicorn（支持热重载）
uvicorn src.main:app --reload

# 方式三：安装后使用命令
x-watcher
```

后端服务默认运行在 `http://localhost:8000`。

### 第三步：启动前端开发服务器

打开一个**新的终端窗口**：

```bash
cd src/web
npm run dev
```

前端开发服务器默认运行在 `http://localhost:5173`，已配置 API 代理自动将 `/api` 请求转发到后端 `http://localhost:8000`。

### 验证启动成功

- 后端健康检查：访问 http://localhost:8000/health
- 后端 API 文档：访问 http://localhost:8000/docs（Swagger UI）
- **前端页面**：访问 **http://localhost:5173**（主要操作入口）

---

## 前端功能验证

前端是一个 Vue 3 单页应用，包含 4 个主要页面。页面顶部导航栏提供三个入口：**推文**、**关注**、**任务**。

### 1. 配置 Admin API Key

这是使用管理功能（关注管理、任务管理）的前提条件。

**操作步骤：**

1. 打开前端页面 http://localhost:5173
2. 注意右上角的**齿轮按钮**——如果显示为红色，表示尚未配置 API Key
3. 点击齿轮按钮，弹出 **API Key 设置对话框**
4. 输入你在 `.env` 文件中设置的 `ADMIN_API_KEY` 值（例如 `my_secret_admin_key`）
5. 点击「保存」，看到提示「API Key 已保存」
6. 齿轮按钮变为灰色，表示配置成功

> API Key 存储在浏览器的 localStorage 中，关闭浏览器后仍然有效。

---

### 2. 关注管理（/follows）

管理系统需要抓取哪些 Twitter 账号的推文。

**操作步骤：**

1. 点击顶部导航栏的「关注」，进入**抓取账号管理**页面
2. 点击右上角「添加账号」按钮
3. 在弹出的对话框中填写：
   - **用户名**：Twitter 用户名，不带 `@` 符号（如 `elonmusk`）
   - **添加理由**：说明为什么关注此账号（至少 5 个字符）
4. 点击「添加」
5. 账号出现在列表中，状态为「活跃」

**其他操作：**

| 操作 | 说明 |
|------|------|
| 编辑 | 修改账号的添加理由 |
| 禁用/启用 | 切换账号的活跃状态，禁用后不再抓取该账号 |
| 删除 | 软删除该账号，会弹出确认对话框 |

---

### 3. 任务监控（/tasks）

管理和监控推文抓取任务的执行状态。

**触发抓取任务：**

1. 点击顶部导航栏的「任务」
2. 点击右上角「立即抓取」按钮
3. 系统开始抓取在「关注管理」中配置的所有活跃账号的推文
4. 页面顶部会显示**当前任务卡片**，展示：
   - 任务 ID
   - 状态（等待中 → 执行中 → 已完成/失败）
   - 实时进度条（执行中时）
   - 执行结果（完成后显示抓取推文数、去重组数、摘要数）

**查看任务历史：**

- 下方「任务历史」表格展示所有历史任务
- 点击任意任务的「详情」可查看完整信息，包括：
  - 创建时间、开始时间、完成时间
  - 进度详情
  - 错误信息（如果失败）
  - 执行结果 JSON

---

### 4. 推文列表（/tweets）

查看系统已抓取的所有推文。

**基本操作：**

1. 点击顶部导航栏的「推文」（首页默认也是此页面）
2. 页面展示所有推文的卡片列表，每个卡片包含：
   - 作者显示名和用户名（如 `Elon Musk @elonmusk`）
   - 发布时间（相对时间，如「2小时前」）
   - 推文内容预览（最多 3 行）
   - 状态标签：「已摘要」/「未摘要」、「已去重」、媒体数量

**按作者筛选：**

1. 在页面顶部的筛选输入框中输入作者用户名
2. 按回车或点击搜索图标
3. 清空输入框可恢复显示全部推文

**翻页：**

- 页面底部提供分页控件
- 可选择每页显示 10/20/50/100 条
- 支持跳转到指定页码

**刷新数据：**

- 点击页面标题旁的「刷新」按钮重新加载数据

---

### 5. 推文详情（/tweets/:id）

查看单条推文的完整内容和 AI 摘要。

**操作步骤：**

1. 在推文列表页面，点击任意推文卡片
2. 进入推文详情页面，展示：

   **推文卡片**：
   - 完整的推文正文
   - 媒体图片（如果有）
   - 精确的发布时间

   **AI 摘要卡片**（如果已生成）：
   - 英文摘要
   - 中文翻译
   - 元信息：使用的 AI 模型、生成成本、是否为缓存

   **去重信息卡片**（如果有相似推文）：
   - 去重组 ID
   - 去重类型（完全重复 / 相似内容）
   - 相似度百分比

3. 点击左上角「返回」按钮回到列表

---

## API 端点总览

除了前端界面，你也可以直接使用 API 来操作系统。

### 功能模块

| 模块 | 前缀 | 功能 | 需要认证 |
|------|------|------|----------|
| 抓取任务 | `/api/admin/scrape` | 推文抓取任务管理 | 否 |
| 抓取配置 | `/api/admin/scraping` | 平台抓取账号管理 | 是（Admin API Key） |
| 推文 | `/api/tweets` | 推文列表和详情查询 | 否 |
| 去重 | `/api/deduplicate` | 推文去重 | 否 |
| 摘要 | `/api/summaries` | AI 摘要生成 | 否 |
| 偏好 | `/api/preferences` | 用户个性化配置 | 否 |
| 监控 | `/metrics` | Prometheus 指标 | 否 |

### 常用 API 示例

#### 手动触发抓取

```bash
curl -X POST "http://localhost:8000/api/admin/scrape" \
  -H "Content-Type: application/json" \
  -d '{"usernames": "elonmusk,sama", "limit": 50}'
```

#### 查看推文列表

```bash
curl "http://localhost:8000/api/tweets?page=1&page_size=20"
# 按作者筛选
curl "http://localhost:8000/api/tweets?author=elonmusk&page=1&page_size=20"
```

#### 批量生成 AI 摘要

```bash
curl -X POST "http://localhost:8000/api/summaries/batch" \
  -H "Content-Type: application/json" \
  -d '{"tweet_ids": ["123", "456"], "force_refresh": false}'
```

#### 批量去重

```bash
curl -X POST "http://localhost:8000/api/deduplicate/batch" \
  -H "Content-Type: application/json" \
  -d '{"tweet_ids": ["123", "456", "789"]}'
```

#### 获取个性化新闻流

```bash
curl "http://localhost:8000/api/preferences/news?user_id=1&sort=relevance&limit=20"
```

#### 查看摘要成本统计

```bash
curl "http://localhost:8000/api/summaries/stats"
```

> 完整 API 文档请访问 Swagger UI：http://localhost:8000/docs

---

## 典型工作流程

以下是一个完整的功能验证流程，从配置到查看 AI 摘要：

### Step 1：准备工作

1. 确保 `.env` 文件已正确配置 API Key
2. 启动后端服务（`python -m src.main`）
3. 启动前端开发服务器（`cd src/web && npm run dev`）
4. 打开浏览器访问 http://localhost:5173

### Step 2：配置 API Key

1. 点击右上角齿轮按钮
2. 输入 `.env` 中的 `ADMIN_API_KEY` 值
3. 保存

### Step 3：添加抓取账号

1. 进入「关注」页面
2. 添加你想关注的 Twitter 账号（如 `elonmusk`、`OpenAI`）

### Step 4：执行抓取

1. 进入「任务」页面
2. 点击「立即抓取」
3. 观察任务执行状态，等待完成
4. 如果启用了 `AUTO_SUMMARIZATION_ENABLED`，抓取完成后会自动生成 AI 摘要

### Step 5：查看结果

1. 进入「推文」页面
2. 查看已抓取的推文列表
3. 点击任意推文查看详情和 AI 摘要
4. 使用作者筛选功能查看特定账号的推文

### Step 6：（可选）配置用户偏好

通过 API 设置个性化偏好：

```bash
# 添加关注（user_id=1 为种子脚本创建的管理员）
curl -X POST "http://localhost:8000/api/preferences/follows?user_id=1" \
  -H "Content-Type: application/json" \
  -d '{"username": "elonmusk", "priority": 9}'

# 添加关键词过滤
curl -X POST "http://localhost:8000/api/preferences/filters?user_id=1" \
  -H "Content-Type: application/json" \
  -d '{"filter_type": "keyword", "value": "AI"}'

# 设置排序方式（time / relevance / priority）
curl -X PUT "http://localhost:8000/api/preferences/sorting?user_id=1" \
  -H "Content-Type: application/json" \
  -d '{"sort_type": "relevance"}'

# 获取个性化新闻流
curl "http://localhost:8000/api/preferences/news?user_id=1&sort=relevance&limit=20"
```

---

## 常见问题

### Q1: 前端页面打开是空白的？

检查以下几点：
- 后端服务是否正在运行（`http://localhost:8000/health` 是否正常返回）
- 前端是否正确安装了依赖（`cd src/web && npm install`）
- 浏览器控制台是否有报错（按 F12 查看）

### Q2: 关注管理页面提示「认证失败」？

- 确认已在前端右上角齿轮按钮中正确配置了 Admin API Key
- 确认 `.env` 中的 `ADMIN_API_KEY` 与前端输入的一致

### Q3: 抓取任务失败？

检查以下项：
- `.env` 中 `TWITTER_API_KEY` 是否正确
- 用户名格式是否正确（不带 `@` 符号）
- 网络是否能访问 `api.twitterapi.io`
- 查看后端终端日志获取详细错误信息

### Q4: 摘要没有自动生成？

- 确认 `.env` 中 `AUTO_SUMMARIZATION_ENABLED=true`
- 确认 `MINIMAX_API_KEY` 已正确配置
- 网络是否能访问 `api.minimaxi.com`
- 也可以手动通过 API 触发摘要生成

### Q5: 如何获取 API Key？

| API Key | 获取方式 |
|---------|----------|
| TwitterAPI.io | 访问 https://twitterapi.io/ 注册，从 Dashboard 获取 |
| MiniMax | 访问 https://api.minimaxi.com/ 注册，创建应用后获取 |
| Admin API Key | 自己设定任意字符串，写入 `.env` 即可 |

### Q6: 如何启用定时自动抓取？

在 `.env` 中设置：
```bash
SCRAPER_ENABLED=true
SCRAPER_INTERVAL=3600
SCRAPER_USERNAMES=elonmusk,OpenAI,nvidia
```

启动后端后，系统会每隔 `SCRAPER_INTERVAL` 秒自动抓取配置的账号。

### Q7: 数据库在哪里？如何重置？

默认使用 SQLite，数据库文件为项目根目录下的 `news_agent.db`。

重置方法：
```bash
# 停止后端服务后删除数据库文件
rm news_agent.db

# 重新启动后端（会自动创建新数据库）
python -m src.main

# 重新运行种子脚本创建管理员
python -m scripts.seed_admin
```

---

## 监控和调试

### 健康检查

```bash
curl "http://localhost:8000/health"
```

### Prometheus 指标

```bash
curl "http://localhost:8000/metrics"
```

### 调整日志级别

在 `.env` 中修改：
```bash
LOG_LEVEL=DEBUG  # 可选：DEBUG, INFO, WARNING, ERROR
```

### API 交互式文档

- **Swagger UI**: http://localhost:8000/docs — 可直接在页面上测试 API
- **ReDoc**: http://localhost:8000/redoc — 更适合阅读的 API 文档格式
