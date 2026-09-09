"""
SLA math: turn a list of raw check rows into the numbers a Production/App
Support team actually reports on -- uptime %, error budget remaining,
incident count, MTTR (mean time to recovery), MTBF (mean time between
failures).

Everything here is time-weighted, not check-count-weighted: a service
checked every 10s that fails for 2 minutes has 2 minutes of downtime,
regardless of whether that was 12 failing checks or 2. That distinction is
exactly the kind of detail that reads well in an interview.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Incident:
    start: float
    end: float  # for an ongoing incident, this is the timestamp of the last check seen so far
    first_error: Optional[str]
    ongoing: bool = False  # True => not yet resolved as of the last check in the window

    @property
    def duration_seconds(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class SLAReport:
    service: str
    target_pct: float
    window_start: Optional[float]
    window_end: Optional[float]
    total_checks: int
    failed_checks: int
    uptime_pct: float
    downtime_seconds: float
    incidents: list[Incident] = field(default_factory=list)
    avg_latency_ms: Optional[float] = None
    p95_latency_ms: Optional[float] = None

    @property
    def incident_count(self) -> int:
        return len(self.incidents)

    @property
    def breached(self) -> bool:
        # No data yet => treat as not-breached rather than a false alarm.
        if self.total_checks == 0:
            return False
        return self.uptime_pct < self.target_pct

    @property
    def error_budget_pct(self) -> float:
        """How much unavailability the SLA target still allows, in percentage points."""
        return round(100.0 - self.target_pct, 4)

    @property
    def error_budget_remaining_pct(self) -> float:
        """Budget left before breaching, in percentage points. Negative = already over."""
        return round(self.uptime_pct - self.target_pct, 4)

    @property
    def mttr_seconds(self) -> Optional[float]:
        """Mean time to recovery across resolved incidents (ongoing ones are excluded --
        we don't know how long they'll last yet)."""
        resolved = [i for i in self.incidents if not i.ongoing]
        if not resolved:
            return None
        return sum(i.duration_seconds for i in resolved) / len(resolved)

    @property
    def mtbf_seconds(self) -> Optional[float]:
        """Mean time between the *start* of one incident and the start of the next."""
        starts = [i.start for i in self.incidents]
        if len(starts) < 2:
            return None
        gaps = [b - a for a, b in zip(starts, starts[1:])]
        return sum(gaps) / len(gaps)


def _percentile(values: list[float], pct: float) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * (pct / 100.0)
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def build_incidents(history: list[dict]) -> list[Incident]:
    """Group consecutive failing checks into discrete incidents.

    A resolved incident's `end` is the timestamp of the first passing check after it.
    An incident still failing at the last check in the window is marked `ongoing`, with
    `end` set to that last check's timestamp so downtime/duration math has something to
    measure against (the incident isn't over -- we just can't see past the data we have).
    """
    incidents: list[Incident] = []
    open_incident: Optional[Incident] = None

    for row in history:
        if not row["ok"]:
            if open_incident is None:
                open_incident = Incident(start=row["timestamp"], end=row["timestamp"], first_error=row.get("error"))
            else:
                open_incident.end = row["timestamp"]  # extend while still failing
        else:
            if open_incident is not None:
                open_incident.end = row["timestamp"]
                open_incident.ongoing = False
                incidents.append(open_incident)
                open_incident = None

    if open_incident is not None:
        open_incident.ongoing = True
        incidents.append(open_incident)

    return incidents


def evaluate(service: str, history: list[dict], target_pct: float) -> SLAReport:
    """Compute a full SLAReport from a service's check history (ascending by timestamp)."""
    if not history:
        return SLAReport(
            service=service,
            target_pct=target_pct,
            window_start=None,
            window_end=None,
            total_checks=0,
            failed_checks=0,
            uptime_pct=100.0,
            downtime_seconds=0.0,
            incidents=[],
        )

    window_start = history[0]["timestamp"]
    window_end = history[-1]["timestamp"]
    total_checks = len(history)
    failed_checks = sum(1 for r in history if not r["ok"])

    incidents = build_incidents(history)
    downtime_seconds = sum(i.duration_seconds for i in incidents)

    total_window = max(window_end - window_start, 0.0)
    if total_window > 0:
        uptime_pct = max(0.0, (total_window - downtime_seconds) / total_window * 100.0)
    else:
        # Single data point: fall back to check-count-based uptime.
        uptime_pct = 100.0 if failed_checks == 0 else 0.0

    latencies = [r["latency_ms"] for r in history if r.get("latency_ms") is not None]
    avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else None
    p95_latency = _percentile(latencies, 95)
    if p95_latency is not None:
        p95_latency = round(p95_latency, 2)

    return SLAReport(
        service=service,
        target_pct=target_pct,
        window_start=window_start,
        window_end=window_end,
        total_checks=total_checks,
        failed_checks=failed_checks,
        uptime_pct=round(uptime_pct, 4),
        downtime_seconds=round(downtime_seconds, 2),
        incidents=incidents,
        avg_latency_ms=avg_latency,
        p95_latency_ms=p95_latency,
    )
