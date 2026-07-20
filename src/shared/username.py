"""严格用户名格式校验（CHG-041）。

本模块只校验格式，不剥离 ``@``、不转换大小写，也不做任何规范化。
"""


def validate_username_format(username: str) -> None:
    """校验用户名为 1-15 位字母、数字或下划线。"""
    if not (1 <= len(username) <= 15):
        raise ValueError(f"用户名 '{username}' 长度必须在 1-15 字符之间")
    if not username.replace("_", "").isalnum():
        raise ValueError(f"用户名 '{username}' 只能包含字母、数字和下划线")


def is_valid_username_format(username: str) -> bool:
    """布尔式判定（跳过型消费方用：解析器/导入过滤）。"""
    return 1 <= len(username) <= 15 and username.replace("_", "").isalnum()
