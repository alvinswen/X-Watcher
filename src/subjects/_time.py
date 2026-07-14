"""Subject 领域时间转换工具。"""

from datetime import datetime

from src.storage import paths


def parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return paths.as_utc(value)
    return paths.as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def iso_z(value: datetime) -> str:
    return paths.as_utc(value).isoformat().replace("+00:00", "Z")
