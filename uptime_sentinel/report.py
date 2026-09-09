"""
Renders a static, single-file HTML dashboard from stored check history.
No JS framework, no build step -- `open report.html` and you're looking at
a status page. That constraint is intentional: it's the same "zero infra"
philosophy as the rest of the project, and it means the dashboard itself is
part of the portfolio artifact (screenshot it, link it in the README).
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from pathlib import Path

from .sla import SLAReport


def _fmt_ts(ts: float | None) -> str:
    if ts is None:
        return "—"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def _status_dot(ok: bool) -> str:
    return "up" if ok else "down"


def _bar_title(row: dict) -> str:
    when = _fmt_ts(row["timestamp"])
    outcome = "OK" if row["ok"] else (row.get("error") or "failed")
    return html.escape(f"{when} — {outcome}")


def _history_bars(history: list[dict], limit: int = 60) -> str:
    """A compact strip of bars, one per recent check -- green up, red down."""
    recent = history[-limit:]
    if not recent:
        return "<div class='bars empty'>no checks recorded yet</div>"
    bars = "".join(
        f"<span class='bar {_status_dot(r['ok'])}' title='{_bar_title(r)}'></span>"
        for r in recent
    )
    return f"<div class='bars'>{bars}</div>"


def render(reports: list[SLAReport], histories: dict[str, list[dict]], generated_at: float) -> str:
    cards = []
    for report in reports:
        breached = report.breached
        latest = histories.get(report.service, [])
        currently_up = latest[-1]["ok"] if latest else None

        status_label = "NO DATA"
        status_class = "unknown"
        if currently_up is True:
            status_label, status_class = "OPERATIONAL", "up"
        elif currently_up is False:
            status_label, status_class = "DOWN", "down"

        budget_class = "over" if report.error_budget_remaining_pct < 0 else "ok"

        cards.append(f"""
        <section class="card">
          <header>
            <div class="title">
              <span class="dot {status_class}"></span>
              <h2>{html.escape(report.service)}</h2>
            </div>
            <span class="badge {status_class}">{status_label}</span>
          </header>

          {_history_bars(latest)}

          <div class="metrics">
            <div class="metric">
              <span class="label">Uptime ({_fmt_ts(report.window_start)} → {_fmt_ts(report.window_end)})</span>
              <span class="value {'breach' if breached else ''}">{report.uptime_pct:.3f}%</span>
            </div>
            <div class="metric">
              <span class="label">SLA target</span>
              <span class="value">{report.target_pct:.2f}%</span>
            </div>
            <div class="metric">
              <span class="label">Error budget remaining</span>
              <span class="value {budget_class}">{report.error_budget_remaining_pct:+.3f} pp</span>
            </div>
            <div class="metric">
              <span class="label">Downtime</span>
              <span class="value">{_fmt_duration(report.downtime_seconds)}</span>
            </div>
            <div class="metric">
              <span class="label">Incidents</span>
              <span class="value">{report.incident_count}</span>
            </div>
            <div class="metric">
              <span class="label">MTTR</span>
              <span class="value">{_fmt_duration(report.mttr_seconds)}</span>
            </div>
            <div class="metric">
              <span class="label">MTBF</span>
              <span class="value">{_fmt_duration(report.mtbf_seconds)}</span>
            </div>
            <div class="metric">
              <span class="label">Avg / p95 latency</span>
              <span class="value">{report.avg_latency_ms or '—'} / {report.p95_latency_ms or '—'} ms</span>
            </div>
            <div class="metric">
              <span class="label">Checks (failed)</span>
              <span class="value">{report.total_checks} ({report.failed_checks})</span>
            </div>
          </div>
        </section>
        """)

    breached_count = sum(1 for r in reports if r.breached)
    overall_class = "down" if breached_count else "up"
    overall_label = f"{breached_count} SERVICE(S) BREACHING SLA" if breached_count else "ALL SYSTEMS WITHIN SLA"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>uptime-sentinel status</title>
<style>
  :root {{
    --bg: #0b0f14; --panel: #131a22; --border: #223041; --text: #e6edf3;
    --muted: #8b98a5; --up: #3fb950; --down: #f85149; --warn: #d29922; --accent: #58a6ff;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 32px 20px 60px; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }}
  .wrap {{ max-width: 980px; margin: 0 auto; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  .sub {{ color: var(--muted); font-size: 13px; margin-bottom: 24px; }}
  .overall {{
    display: inline-flex; align-items: center; gap: 8px; padding: 8px 14px; border-radius: 8px;
    font-weight: 600; font-size: 13px; letter-spacing: .03em; margin-bottom: 28px;
    border: 1px solid var(--border);
  }}
  .overall.up {{ color: var(--up); }}
  .overall.down {{ color: var(--down); }}
  .card {{
    background: var(--panel); border: 1px solid var(--border); border-radius: 12px;
    padding: 20px 22px; margin-bottom: 18px;
  }}
  .card header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }}
  .title {{ display: flex; align-items: center; gap: 10px; }}
  .title h2 {{ font-size: 16px; margin: 0; font-weight: 600; }}
  .dot {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }}
  .dot.up {{ background: var(--up); }}
  .dot.down {{ background: var(--down); }}
  .dot.unknown {{ background: var(--muted); }}
  .badge {{ font-size: 11px; font-weight: 700; letter-spacing: .04em; padding: 3px 8px; border-radius: 6px; }}
  .badge.up {{ color: var(--up); background: rgba(63,185,80,.12); }}
  .badge.down {{ color: var(--down); background: rgba(248,81,73,.12); }}
  .badge.unknown {{ color: var(--muted); background: rgba(139,152,165,.12); }}
  .bars {{ display: flex; gap: 2px; margin-bottom: 16px; height: 24px; align-items: flex-end; }}
  .bars.empty {{ color: var(--muted); font-size: 12px; align-items: center; }}
  .bar {{ flex: 1; min-width: 2px; height: 100%; border-radius: 2px; background: var(--border); }}
  .bar.up {{ background: var(--up); }}
  .bar.down {{ background: var(--down); }}
  .metrics {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 14px; }}
  .metric {{ display: flex; flex-direction: column; gap: 3px; }}
  .metric .label {{ font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .03em; }}
  .metric .value {{ font-size: 17px; font-weight: 600; font-variant-numeric: tabular-nums; }}
  .value.breach {{ color: var(--down); }}
  .value.ok {{ color: var(--up); }}
  .value.over {{ color: var(--down); }}
  footer {{ color: var(--muted); font-size: 12px; margin-top: 20px; text-align: center; }}
  a {{ color: var(--accent); }}
  @media (prefers-color-scheme: light) {{
    :root {{
      --bg: #f6f8fa; --panel: #ffffff; --border: #d0d7de; --text: #1f2328; --muted: #656d76;
    }}
  }}
</style>
</head>
<body>
  <div class="wrap">
    <h1>uptime-sentinel</h1>
    <div class="sub">Service health &amp; SLA dashboard &middot; generated {html.escape(_fmt_ts(generated_at))}</div>
    <div class="overall {overall_class}">{overall_label}</div>
    {''.join(cards) if cards else '<p style="color:var(--muted)">No services checked yet. Run <code>uptime-sentinel run --once</code> first.</p>'}
    <footer>uptime-sentinel &middot; github.com/Trenddy/uptime-sentinel</footer>
  </div>
</body>
</html>
"""


def write_report(reports: list[SLAReport], histories: dict[str, list[dict]], out_path: str, generated_at: float) -> str:
    content = render(reports, histories, generated_at)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(content, encoding="utf-8")
    return out_path
