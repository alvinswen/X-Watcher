"""Prometheus 指标定义。

定义所有应用级别的 Prometheus 监控指标。
"""

from prometheus_client import Counter, Gauge, Histogram

# HTTP 请求计数器
# 标签: method (HTTP 方法), path (请求路径), status (HTTP 状态码)
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)

# HTTP 请求延迟直方图
# 标签: method (HTTP 方法), path (请求路径)
# 分桶: 0.005s, 0.01s, 0.025s, 0.05s, 0.075s, 0.1s, 0.25s, 0.5s, 0.75s, 1.0s, 2.5s, 5.0s, 7.5s, 10.0s
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0),
)

# 活跃任务数
active_tasks = Gauge(
    "active_tasks",
    "Number of active tasks",
)

# 任务总数计数器
# 标签: status (任务状态: pending, running, completed, failed)
tasks_total = Counter(
    "tasks_total",
    "Total tasks by status",
    ["status"],
)

# 数据库连接池大小
db_pool_size = Gauge(
    "db_pool_size",
    "Database connection pool size",
)

# 数据库可用连接数
db_pool_available = Gauge(
    "db_pool_available",
    "Available database connections",
)

# 调度器任务指标
scheduler_job_executed_total = Counter(
    "scheduler_job_executed_total",
    "Total successful scheduler job executions",
    ["job_id"],
)

scheduler_job_error_total = Counter(
    "scheduler_job_error_total",
    "Total scheduler job errors",
    ["job_id"],
)

scheduler_job_missed_total = Counter(
    "scheduler_job_missed_total",
    "Total missed scheduler job executions",
    ["job_id"],
)

scheduler_job_duration_seconds = Gauge(
    "scheduler_job_duration_seconds",
    "Duration of last scheduler job execution in seconds",
    ["job_id"],
)

# 摘要队列指标
summarization_queue_size = Gauge(
    "summarization_queue_size",
    "Current items in summarization queue",
)

summarization_queue_enqueued_total = Counter(
    "summarization_queue_enqueued_total",
    "Total items enqueued to summarization queue",
    ["source"],  # scraping/deduplication/batch_api/retry
)

summarization_queue_processed_total = Counter(
    "summarization_queue_processed_total",
    "Total items processed from summarization queue",
    ["status"],  # success/failure
)

summarization_queue_dropped_total = Counter(
    "summarization_queue_dropped_total",
    "Items dropped due to full summarization queue",
)
