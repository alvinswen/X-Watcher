"""save_summaries 文件交接（handoff）通道公共校验 · CHG-066。

批级闸公共 helper：路径白名单 / 常规文件检查 / 读取与大小 / 指纹比对 / 禁转义扫描 / JSON 解析。
follow-up（put_subject_digest / put_subject_review 同根因改造）复用本模块，
保证三个写回工具口径逐字一致（01 § 4.6）。
本模块只依赖 stdlib，保持域中立（勿引入 subjects/summarization 等领域模块）。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HANDOFF_DIR_NAME = "handoff"
MAX_HANDOFF_BYTES = 10 * 1024 * 1024  # 10,485,760 字节（Gate1 Q6 · 恰等于放行）

# 批级拒绝分类（稳定机器可读 · Q3=A · 场景 9 复用 sha256_mismatch）
BATCH_INVALID_PARAM_COMBO = "invalid_param_combo"
BATCH_PATH_NOT_ALLOWED = "path_not_allowed"
BATCH_FILE_UNREADABLE = "file_unreadable"
BATCH_FILE_TOO_LARGE = "file_too_large"
BATCH_SHA256_MISMATCH = "sha256_mismatch"
BATCH_ESCAPED_UNICODE_FOUND = "escaped_unicode_found"
BATCH_INVALID_JSON = "invalid_json"
BATCH_NOT_AN_ARRAY = "not_an_array"

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
# 真转义扫描（Q4 边界 1 精确扫）：从非反斜杠边界起，吃偶数对反斜杠后仍剩
# 单个反斜杠紧邻 u+4hex = JSON 层真转义（奇数反斜杠）→ 命中；偶数（字面
# 文本）不命中。短转义（反斜杠+字母）非本形态，天然不在扫描面（01 § 4.3.b）。
_TRUE_ESCAPE_RE = re.compile(r"(?<!\\)(?:\\\\)*(\\u[0-9a-fA-F]{4})")

# 通用指引文案（不含具体工具参数名 · follow-up 逐字复用）
GUIDANCE_PATH_NOT_ALLOWED = (
    "提交的文件路径不在白名单：只接受交接目录直下的 .json 常规文件"
    "（不收子目录、不跟符号链接、不收其他扩展名；非常规文件——硬链接/管道等——不收）。"
    "交接目录定位见工具说明书（服务端数据根直下的 handoff/ 子目录）；"
    "请把文件写到该目录直下、.json 扩展名、传绝对路径后重提。"
)
GUIDANCE_FILE_UNREADABLE = (
    "交接文件不存在或读取失败：请确认已用 Write 工具落盘、"
    "调用传入的路径与写入路径逐字一致后重提。"
)
GUIDANCE_FILE_TOO_LARGE = (
    "交接文件超过 10MB 上限（10,485,760 字节）：请拆成多个文件分批调用；"
    "内容无需重新生成。"
)
GUIDANCE_SHA256_MISMATCH = (
    "提交的指纹与服务端对文件原始字节重算值不符：文件可能在算指纹后被改动或覆盖"
    "（并发写同名文件会表现为此拒绝），或指纹算错对象（须对文件原始字节整体计算，"
    "非文本、非逐条）。请以新文件名重写文件（勿覆盖原文件——被拒文件保留作排查物证）、"
    "重算指纹后重提；内容无需重新生成。"
)
GUIDANCE_SHA256_FORMAT = (
    "指纹须为 64 位十六进制串（对交接文件原始字节整体计算的 sha256，大小写不敏感）。"
    "请重算指纹后重提；文件与内容无需改动。"
)
GUIDANCE_ESCAPED_TEMPLATE = (
    "交接文件含真转义序列（单个反斜杠+u+4 位十六进制，命中 {count} 处，"
    "首处字符偏移 {offset}：{seq}）：该转义路径已实证必然产生等长形近字转录漂移。"
    "请用 UTF-8 直写方式重新序列化（非 ASCII 一律原样字符）为新文件后重提"
    "（勿覆盖原文件——被拒文件保留作排查物证）；若因正文含控制字符被强制转义，"
    "请先清理控制字符。双反斜杠字面文本与换行/制表等短转义不受影响；"
    "内容无需重新生成。"
)
GUIDANCE_JSON_BOM = (
    "交接文件带 UTF-8 BOM：请以 UTF-8 无 BOM 重新序列化写入新文件后重提"
    "（勿覆盖原文件——被拒文件保留作排查物证）；内容无需重新生成。"
)
GUIDANCE_JSON_NOT_UTF8 = (
    "交接文件不是 UTF-8 编码：请转为 UTF-8（无 BOM）写入新文件后重提"
    "（勿覆盖原文件）；内容无需重新生成。"
)
GUIDANCE_JSON_SYNTAX = (
    "交接文件不是合法 JSON：请重新序列化为规范 JSON（UTF-8 无 BOM）写入新文件后重提"
    "（勿覆盖原文件——被拒文件保留作排查物证）；内容无需重新生成。"
)


@dataclass(frozen=True)
class HandoffRejection:
    """批级拒绝：稳定分类 + 改正指引。"""

    category: str
    guidance: str


@dataclass(frozen=True)
class HandoffPayload:
    """批级闸全过：解析产物 + 服务端重算指纹（小写）+ 字节数。"""

    parsed: Any
    file_sha256: str
    byte_size: int


def handoff_dir(data_root: Path) -> Path:
    """交接目录 = 数据根直下 handoff/（Gate1 Q1=A）。非分片，不进 storage/paths.py。"""
    return Path(data_root) / HANDOFF_DIR_NAME


def batch_error_response(category: str, guidance: str) -> str:
    """批级拒绝响应：与 helpers.error_response 同形 + batch_category 附加键。"""
    return json.dumps(
        {
            "success": False,
            "error": guidance,
            "error_type": "validation",
            "batch_category": category,
        },
        ensure_ascii=False,
    )


def load_handoff_file(
    data_root: Path, raw_path: str, claimed_sha256: str
) -> HandoffPayload | HandoffRejection:
    """文件通道批级闸 2~7（顶层形状判定留调用方——各工具同构面不同）。

    顺序（Gate1 锁定 + A5 加固②）：指纹格式 → 路径白名单三重 → 常规文件检查
    （S_ISREG + nlink==1 · open 之前）→ 读取(存在/大小) → 指纹比对 →
    UTF-8 解码+BOM（编码子情形归 invalid_json 分类）→ 真转义扫描 → JSON 解析。
    内容判定全部作用于同一份已读字节（TOCTOU-free）。
    """
    # 闸 2a · 指纹格式（归一 strip+lower · 忽略大小写裁定见 03 § 5.3；
    # 畸形指纹永不可能通过比对，提前失败免读 10MB，分类结果与晚判一致）
    fingerprint = claimed_sha256.strip().lower()
    if not _SHA256_HEX_RE.match(fingerprint):
        return HandoffRejection(BATCH_SHA256_MISMATCH, GUIDANCE_SHA256_FORMAT)

    # 闸 2b · 路径白名单三重判定（Q1=A 最严：恰父目录 + .json + 非符号链接）
    try:
        literal = Path(raw_path)
        if literal.suffix != ".json":
            return HandoffRejection(BATCH_PATH_NOT_ALLOWED, GUIDANCE_PATH_NOT_ALLOWED)
        expected_dir = handoff_dir(data_root).resolve()
        target = literal.resolve()
        if target.parent != expected_dir or target.suffix != ".json":
            return HandoffRejection(BATCH_PATH_NOT_ALLOWED, GUIDANCE_PATH_NOT_ALLOWED)
        if literal.is_symlink():
            return HandoffRejection(BATCH_PATH_NOT_ALLOWED, GUIDANCE_PATH_NOT_ALLOWED)
    except (OSError, ValueError):
        return HandoffRejection(BATCH_PATH_NOT_ALLOWED, GUIDANCE_PATH_NOT_ALLOWED)

    # 闸 2c · 常规文件检查（A5 加固②：拒硬链接分身与 FIFO 假管道——硬链接可
    # 读出目录外内容、FIFO 进 open 读取会永久阻塞长驻进程；必须 open 之前以 stat 判）
    try:
        st = os.stat(target)
    except OSError:
        # 含 FileNotFoundError：不存在文件在此拦（拦截点较 v1 提前 · 分类不变=场景 3）
        return HandoffRejection(BATCH_FILE_UNREADABLE, GUIDANCE_FILE_UNREADABLE)
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        return HandoffRejection(BATCH_PATH_NOT_ALLOWED, GUIDANCE_PATH_NOT_ALLOWED)

    # 闸 3/4 · 读取（场景 3 兜底：stat 后文件被删/权限拒 → OSError）+ 大小
    # （read(MAX+1) 判超限）
    try:
        with open(target, "rb") as fh:
            data = fh.read(MAX_HANDOFF_BYTES + 1)
    except OSError:
        return HandoffRejection(BATCH_FILE_UNREADABLE, GUIDANCE_FILE_UNREADABLE)
    if len(data) > MAX_HANDOFF_BYTES:
        return HandoffRejection(BATCH_FILE_TOO_LARGE, GUIDANCE_FILE_TOO_LARGE)

    # 闸 5 · 指纹比对（fail-closed 核心）
    actual = hashlib.sha256(data).hexdigest()
    if actual != fingerprint:
        return HandoffRejection(BATCH_SHA256_MISMATCH, GUIDANCE_SHA256_MISMATCH)

    # 闸 6 · UTF-8 无 BOM（编码子情形归 invalid_json 分类 · 01 § 4.3.b）
    if data.startswith(b"\xef\xbb\xbf"):
        return HandoffRejection(BATCH_INVALID_JSON, GUIDANCE_JSON_BOM)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return HandoffRejection(BATCH_INVALID_JSON, GUIDANCE_JSON_NOT_UTF8)

    # 闸 7 · 真转义扫描（对已读字节的解码文本——反斜杠为 ASCII，与字节面等价）
    hits = list(_TRUE_ESCAPE_RE.finditer(text))
    if hits:
        first = hits[0]
        return HandoffRejection(
            BATCH_ESCAPED_UNICODE_FOUND,
            GUIDANCE_ESCAPED_TEMPLATE.format(
                count=len(hits), offset=first.start(1), seq=first.group(1)
            ),
        )

    # 闸 8 · JSON 解析（顶层数组判定留调用方）
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return HandoffRejection(BATCH_INVALID_JSON, GUIDANCE_JSON_SYNTAX)

    return HandoffPayload(parsed=parsed, file_sha256=actual, byte_size=len(data))
