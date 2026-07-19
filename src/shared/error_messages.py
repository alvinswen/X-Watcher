"""REST 错误可见面固定文案集中定义（CHG-037）。

原则：文案说清“出了什么事”与“用户能做什么”；
不含内部路径、异常类名、堆栈或上游服务原文。
存量 curated 文案不迁入本模块，仅本包新收口点与全局兜底文案落此。
本模块为纯常量层，禁止导入本项目其他模块。
"""

# —— 全局兜底（main.py · 第 4 口径）——
INTERNAL_SERVER_ERROR_DETAIL = "服务器内部错误，请稍后重试"

# —— L1 泛异常收口（4 处 · 500）——
TWEETS_LIST_QUERY_FAILED = "查询推文列表失败，请稍后重试"
TWEETS_DETAIL_QUERY_FAILED = "查询推文详情失败，请稍后重试"
SUMMARY_QUERY_FAILED = "查询推文摘要失败，请稍后重试"
ARTICLE_BACKFILL_FAILED = "Article 回溯失败，请稍后重试"

# —— L2 解析/校验收口（4 处 · 状态码逐处保持）——
SYNC_JSON_PARSE_FAILED_TMPL = (
    "JSON 解析失败: 文件第 {lineno} 行第 {colno} 列附近存在格式错误，请检查导入文件后重试"
)
SYNC_EXPORT_FILE_MISSING_FIELD_TMPL = "导出文件解析失败: 缺少必需字段 '{field}'，请重新导出后再导入"
SYNC_EXPORT_FILE_PARSE_FAILED = "导出文件解析失败: 文件内容不符合导出格式，请重新导出后再导入"
SEARCH_TIME_FORMAT_INVALID_TMPL = (
    "时间格式无效: {name} 参数值 '{value}' 不是合法的 ISO 8601 时间，"
    "请使用如 2026-01-01T00:00:00+00:00 的格式"
)

# update_user 路径 ValueError 当前唯一来源为 user_service.py 的最后管理员保护。
# 若该路径未来新增 ValueError 来源，必须同步改为显式映射并更新逐字测试。
USER_LAST_ADMIN_DEMOTE_REFUSED = "不能将最后一个管理员降级为普通用户"
