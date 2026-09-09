from uptime_sentinel.sla import build_incidents, evaluate


def _row(ts: float, ok: bool, latency: float = 10.0, error: str | None = None) -> dict:
    return {"service": "svc", "check_type": "http", "ok": ok, "status_code": 200 if ok else 503,
            "latency_ms": latency, "error": error, "timestamp": ts}


def test_no_history_defaults_to_full_uptime_and_not_breached():
    report = evaluate("svc", [], target_pct=99.9)
    assert report.total_checks == 0
    assert report.uptime_pct == 100.0
    assert report.breached is False


def test_all_healthy_checks_yield_full_uptime():
    history = [_row(i * 60, True) for i in range(10)]
    report = evaluate("svc", history, target_pct=99.9)
    assert report.uptime_pct == 100.0
    assert report.incident_count == 0
    assert report.breached is False
    assert report.mttr_seconds is None


def test_single_incident_reduces_uptime_and_is_measured():
    # Checks every 60s over 10 minutes; checks 4 and 5 (240s-300s) are down => 60s of downtime.
    history = [_row(i * 60, ok=not (4 <= i <= 4)) for i in range(10)]
    report = evaluate("svc", history, target_pct=99.9)

    assert report.incident_count == 1
    assert report.downtime_seconds == 60.0
    # window is 0..540s = 540s total; 60s down => uptime = (540-60)/540 * 100
    assert round(report.uptime_pct, 2) == round((540 - 60) / 540 * 100, 2)
    assert report.breached is True  # well below 99.9%


def test_ongoing_incident_counts_as_downtime_to_the_last_check():
    history = [_row(0, True), _row(60, True), _row(120, False, error="timeout"), _row(180, False, error="timeout")]
    report = evaluate("svc", history, target_pct=99.9)
    assert report.incident_count == 1
    incident = report.incidents[0]
    assert incident.ongoing is True  # still open as of the last check
    assert incident.duration_seconds == 60.0  # 120 -> 180


def test_build_incidents_groups_consecutive_failures():
    history = [
        _row(0, True), _row(10, False), _row(20, False), _row(30, True),
        _row(40, True), _row(50, False), _row(60, True),
    ]
    incidents = build_incidents(history)
    assert len(incidents) == 2
    assert incidents[0].start == 10 and incidents[0].end == 30
    assert incidents[1].start == 50 and incidents[1].end == 60


def test_error_budget_remaining_goes_negative_on_breach():
    history = [_row(i * 60, ok=(i != 5)) for i in range(10)]
    report = evaluate("svc", history, target_pct=99.99)
    assert report.error_budget_remaining_pct < 0
    assert report.breached is True


def test_latency_percentiles_computed():
    history = [_row(i, True, latency=float(i)) for i in range(1, 101)]  # 1..100
    report = evaluate("svc", history, target_pct=99.9)
    assert report.avg_latency_ms == 50.5
    assert 94 <= report.p95_latency_ms <= 96
