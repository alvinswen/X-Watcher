"""x-watcher views 命令族：by-day 派生视图的自查（只读）与重建（会重写副本）。

本机运维专用，沿用 init / validate / export / import-data 的无鉴权惯例。
"""

from __future__ import annotations

from typing import Any

import click

_PREVIEW = 20


def _print_bucket(title: str, items: list[Any], full: bool) -> None:
    click.echo(f"  {title}: {len(items)} 条")
    if not items:
        return
    shown = items if full else items[:_PREVIEW]
    for entry in shown:
        click.echo(f"    - {entry}")
    if not full and len(items) > _PREVIEW:
        click.echo(f"    …（仅显示前 {_PREVIEW} 条，共 {len(items)} 条；--full 查看完整清单）")


@click.group()
def views() -> None:
    """by-day 派生视图运维命令。"""


@views.command("check")
@click.option("--full", is_flag=True, help="打印完整明细（默认每类只显前 20 条）")
def check(full: bool) -> None:
    """自查：校验按天索引副本与推文正本是否一致（只读，不改数据）。"""
    from src.data_layer.provider import data_root
    from src.storage.views import reconcile_by_day

    root = data_root()
    click.echo(f"数据根目录: {root}")
    try:
        ok, detail = reconcile_by_day(root)
    except Exception as exc:  # noqa: BLE001
        raise click.ClickException(f"自查执行失败: {type(exc).__name__}: {exc}") from exc

    click.echo(
        f"计数: 推文正本 {detail['canonical_count']} 条 / 按天索引副本 {detail['view_count']} 条"
    )
    click.echo(
        "  正本有副本无: {a} · 副本有正本无: {b} · 内容不一致: {c} · 归档日错位: {d}".format(
            a=len(detail["only_canonical"]),
            b=len(detail["only_view"]),
            c=len(detail["content_mismatch"]),
            d=len(detail["misplaced"]),
        )
    )
    click.echo(f"结论: {'一致' if ok else '不一致'}")
    if not ok:
        _print_bucket("正本有副本无", detail["only_canonical"], full)
        _print_bucket("副本有正本无", detail["only_view"], full)
        _print_bucket("内容不一致", detail["content_mismatch"], full)
        _print_bucket("归档日错位", detail["misplaced"], full)
        raise SystemExit(1)


@views.command("rebuild")
@click.option("--yes", is_flag=True, help="跳过确认")
def rebuild(yes: bool) -> None:
    """重建：强制重建按天索引副本（会重写副本文件）。"""
    from src.data_layer.provider import data_root
    from src.storage import paths
    from src.storage.views import rebuild_by_day

    root = data_root()
    click.echo(f"数据根目录: {root}")
    click.echo(f"将重写目录: {paths.by_day_dir(root)}")
    click.echo(f"将重写现场记录: {paths.by_day_state_doc(root)}")
    click.echo(f"当前按天分片数: {len(paths.iter_by_day_shards(root))}")
    if not yes:
        click.confirm("确认执行重建？", abort=True)

    stats = rebuild_by_day(root)
    click.echo(f"完成: 产出 {stats['days']} 天 · 清理幽灵 {stats['stale']} 天")
