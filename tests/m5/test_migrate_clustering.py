from datetime import datetime


class _FakeRunOrm:
    id = 1
    status = "completed"
    cut_height = 0.5
    num_clusters = 4
    num_accounts = 58
    num_excluded = 2
    min_tweets_threshold = 20
    linkage_method = "average"
    linkage_matrix_json = "[]"
    account_labels_json = "{}"
    error_message = None
    created_at = datetime(2030, 1, 1)
    completed_at = datetime(2030, 1, 1, 1, 0)


class _FakeAssignOrm:
    id = 9
    run_id = 1
    username = "dave"
    cluster_id = 2
    hourly_distribution_json = "[0,1]"
    tweet_count = 12
    is_manual_override = False


def test_clustering_mappers():
    from src.data_layer.migration.clustering import (
        _assignment_to_domain, _run_to_domain,
    )
    r = _run_to_domain(_FakeRunOrm())
    assert r.id == 1 and r.status.value == "completed"     # str→enum coerce
    assert r.created_at == datetime(2030, 1, 1)
    assert r.completed_at == datetime(2030, 1, 1, 1, 0)
    a = _assignment_to_domain(_FakeAssignOrm())
    assert a.id == 9 and a.run_id == 1 and a.username == "dave"
    assert a.is_manual_override is False
