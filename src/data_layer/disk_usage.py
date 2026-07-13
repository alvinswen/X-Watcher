"""File data-root disk usage helpers."""


def get_database_size_mb() -> float | None:
    """获取当前数据根目录大小（MB）。"""
    from src.data_layer.provider import data_root

    root = data_root()
    if not root.exists():
        return None
    try:
        total = sum(
            p.stat().st_size for p in root.rglob("*") if p.is_file()
        )
        return round(total / (1024 * 1024), 2)
    except OSError:
        return None
