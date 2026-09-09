from uptime_sentinel.monitor import CheckResult
from uptime_sentinel.storage import Store


def _result(service: str, ts: float, ok: bool = True) -> CheckResult:
    return CheckResult(
        service=service, check_type="http", ok=ok, status_code=200 if ok else 500,
        latency_ms=12.3, error=None if ok else "boom", timestamp=ts,
    )


def test_save_and_history_round_trip(tmp_path):
    store = Store(str(tmp_path / "test.db"))
    store.save(_result("api", 100.0))
    store.save(_result("api", 200.0, ok=False))

    history = store.history("api")
    assert len(history) == 2
    assert history[0]["timestamp"] == 100.0
    assert history[1]["ok"] is False  # normalized back from sqlite's 0/1


def test_history_filters_by_since_ts(tmp_path):
    store = Store(str(tmp_path / "test.db"))
    for ts in (100.0, 200.0, 300.0):
        store.save(_result("api", ts))

    recent = store.history("api", since_ts=200.0)
    assert [r["timestamp"] for r in recent] == [200.0, 300.0]


def test_services_lists_distinct_names(tmp_path):
    store = Store(str(tmp_path / "test.db"))
    store.save(_result("api", 1.0))
    store.save(_result("db", 1.0))
    store.save(_result("api", 2.0))
    assert store.services() == ["api", "db"]


def test_latest_returns_most_recent_row(tmp_path):
    store = Store(str(tmp_path / "test.db"))
    store.save(_result("api", 1.0, ok=True))
    store.save(_result("api", 2.0, ok=False))
    latest = store.latest("api")
    assert latest["timestamp"] == 2.0
    assert latest["ok"] is False


def test_save_many_bulk_inserts(tmp_path):
    store = Store(str(tmp_path / "test.db"))
    results = [_result("api", float(i)) for i in range(50)]
    store.save_many(results)
    assert len(store.history("api")) == 50
