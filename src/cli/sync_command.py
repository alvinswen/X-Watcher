"""数据同步 CLI 命令。

export / import-data 子命令。
"""

import platform
from datetime import datetime, timezone
from pathlib import Path

import click

from src.sync.domain.models import ConflictStrategy, SyncCategory


@click.command()
@click.option(
    "--categories",
    default=None,
    help="要导出的分类，逗号分隔 (config,content,topics)，默认全部",
)
@click.option(
    "--output",
    "output_path",
    default=None,
    type=click.Path(),
    help="输出文件路径，默认 x-watcher-export-{timestamp}.json",
)
@click.option("--since", default=None, help="仅导出此时间之后的 content（ISO 8601）")
@click.option("--until", default=None, help="仅导出此时间之前的 content（ISO 8601）")
@click.option("--authors", default=None, help="仅导出指定作者的 content，逗号分隔")
@click.option("--instance-id", default=None, help="来源实例标识，默认 hostname")
@click.option("--pretty", is_flag=True, help="美化 JSON 输出")
def export(
    categories: str | None,
    output_path: str | None,
    since: str | None,
    until: str | None,
    authors: str | None,
    instance_id: str | None,
    pretty: bool,
) -> None:
    """导出数据库数据为 JSON 文件。"""
    from src.sync.format.json_format import write_export_file
    from src.sync.services.export_service import ExportService

    # 解析参数
    cats = _parse_categories(categories)
    since_dt = _parse_datetime(since, "since")
    until_dt = _parse_datetime(until, "until")
    author_list = [a.strip() for a in authors.split(",")] if authors else None
    inst_id = instance_id or platform.node() or "unknown"

    if output_path is None:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = f"x-watcher-export-{ts}.json"

    # 执行导出
    svc = ExportService()
    pkg = svc.export(
        categories=cats,
        since=since_dt,
        until=until_dt,
        authors=author_list,
        instance_id=inst_id,
    )

    path = Path(output_path)
    write_export_file(pkg, path, pretty=pretty)

    # 输出摘要
    click.echo(f"导出完成: {path}")
    click.echo(f"  来源实例: {inst_id}")
    click.echo(f"  分类: {', '.join(pkg.metadata.categories)}")
    for table, count in sorted(pkg.metadata.counts.items()):
        click.echo(f"  {table}: {count}")


@click.command("import-data")
@click.argument("file", type=click.Path(exists=True))
@click.option(
    "--categories",
    default=None,
    help="仅导入文件中的指定分类，逗号分隔",
)
@click.option(
    "--strategy",
    default="skip",
    type=click.Choice(["skip", "overwrite", "merge"], case_sensitive=False),
    help="冲突策略: skip（默认）| overwrite | merge",
)
@click.option("--dry-run", is_flag=True, help="预览模式，不实际修改数据库")
@click.option("--force", is_flag=True, help="跳过 schema 版本兼容性检查")
def import_data(
    file: str,
    categories: str | None,
    strategy: str,
    dry_run: bool,
    force: bool,
) -> None:
    """从 JSON 文件导入数据到数据库。"""
    from src.sync.format.json_format import read_export_file
    from src.sync.services.import_service import ImportService

    path = Path(file)

    # 读取文件
    try:
        pkg = read_export_file(path, force=force)
    except ValueError as e:
        click.echo(f"错误: {e}", err=True)
        raise SystemExit(1)

    click.echo(f"文件: {path}")
    click.echo(f"  导出时间: {pkg.metadata.exported_at}")
    click.echo(f"  来源实例: {pkg.metadata.source_instance_id}")
    click.echo(f"  包含分类: {', '.join(pkg.metadata.categories)}")

    # 解析参数
    cats = _parse_categories(categories)
    conflict_strategy = ConflictStrategy(strategy)

    if dry_run:
        click.echo("\n[预览模式] 不会实际修改数据库")

    # 执行导入
    svc = ImportService()
    result = svc.import_data(
        package=pkg,
        categories=cats,
        strategy=conflict_strategy,
        dry_run=dry_run,
    )

    # 输出结果
    click.echo(f"\n策略: {strategy}")
    for table, stats in sorted(result.stats.items()):
        parts = []
        if stats.inserted:
            parts.append(f"插入 {stats.inserted}")
        if stats.updated:
            parts.append(f"更新 {stats.updated}")
        if stats.skipped:
            parts.append(f"跳过 {stats.skipped}")
        if stats.errors:
            parts.append(f"错误 {stats.errors}")
        click.echo(f"  {table}: {', '.join(parts) or '无变更'}")

    if result.errors:
        click.echo("\n错误:")
        for err in result.errors:
            click.echo(f"  - {err}")

    if result.success:
        click.echo("\n导入完成!")
    else:
        click.echo("\n导入部分失败，请查看上方错误信息。")
        raise SystemExit(1)


def _parse_categories(raw: str | None) -> list[SyncCategory] | None:
    if raw is None:
        return None
    cats = []
    for c in raw.split(","):
        c = c.strip()
        try:
            cats.append(SyncCategory(c))
        except ValueError:
            click.echo(f"警告: 未知分类 '{c}'，已忽略", err=True)
    return cats or None


def _parse_datetime(raw: str | None, name: str) -> datetime | None:
    if raw is None:
        return None
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        click.echo(f"错误: {name} 格式无效 '{raw}'，请使用 ISO 8601", err=True)
        raise SystemExit(1)
