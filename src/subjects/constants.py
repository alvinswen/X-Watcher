"""Subject 领域共享常量。"""

REVIEW_PENDING_MESSAGE = "综述刷新已加入待综述队列，外部技能将异步处理"
REVIEW_MIGRATED_MESSAGE = "综述生成已迁移至外部技能，全量刷新入口暂不批量挂待办"
SUBJECT_NOT_FOUND_HINT = "议题不存在，请先调用 list_subjects 获取有效 subject_id"
SUBJECT_NOT_FOUND = "议题不存在"
MAX_ACTIVE_SUBJECTS = 20
NO_LIMIT = 10**12
