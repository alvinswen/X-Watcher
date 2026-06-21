"""迁移单元注册表。各 migrator 模块在 import 时把自己注册进 MIGRATORS。"""
MIGRATORS = {}  # entity name -> async (session, data_root) -> MigrationReport


def register(name):
    def deco(fn):
        MIGRATORS[name] = fn
        return fn
    return deco
