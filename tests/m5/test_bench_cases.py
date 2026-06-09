import os

from src.data_layer.bench.cases import data_layer_mode


def test_data_layer_mode_sets_and_restores_env():
    os.environ.pop("XWATCHER_DATA_LAYER", None)
    os.environ.pop("XWATCHER_DATA_ROOT", None)
    with data_layer_mode("file", data_root="/tmp/xw-bench-x"):
        assert os.environ["XWATCHER_DATA_LAYER"] == "file"
        assert os.environ["XWATCHER_DATA_ROOT"] == "/tmp/xw-bench-x"
    # 退出后还原(原本未设 → 删除)
    assert "XWATCHER_DATA_LAYER" not in os.environ
    assert "XWATCHER_DATA_ROOT" not in os.environ


def test_data_layer_mode_restores_prior_value():
    os.environ["XWATCHER_DATA_LAYER"] = "sqlalchemy"
    with data_layer_mode("file", data_root="/tmp/xw-bench-y"):
        assert os.environ["XWATCHER_DATA_LAYER"] == "file"
    assert os.environ["XWATCHER_DATA_LAYER"] == "sqlalchemy"
    os.environ.pop("XWATCHER_DATA_LAYER", None)
