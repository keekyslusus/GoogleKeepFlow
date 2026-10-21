"""Summarize api_usage.log: Google requests per day and source, plus the busiest hours.

Usage: python scripts/api_usage_summary.py [path to api_usage.log]
"""
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path


DEFAULT_LOG = Path(os.environ.get("APPDATA", "")) / "FlowLauncher" / "Settings" / "Plugins" / "GoogleKeepFlow" / "api_usage.log"
COLUMNS = ("entries", "requests", "auth_requests", "rate_limited", "request_errors", "runs", "pushes", "pulls")
TOP_HOURS = 5


def load_records(path):
    records = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("time"):
            records.append(record)
    return records


def summarize(records):
    by_day = defaultdict(Counter)
    by_hour = Counter()
    for record in records:
        day = record["time"][:10]
        source = record.get("source", "?")
        totals = by_day[(day, source)]
        totals["entries"] += 1
        for key in COLUMNS[1:]:
            totals[key] += int(record.get(key, 0) or 0)
        by_hour[record["time"][:13]] += int(record.get("requests", 0) or 0) + int(record.get("auth_requests", 0) or 0)
    return by_day, by_hour


def format_report(by_day, by_hour):
    widths = [10, 18] + [max(8, len(name)) for name in COLUMNS]
    header = ["day", "source", *COLUMNS]
    lines = ["  ".join(name.ljust(width) for name, width in zip(header, widths))]
    for (day, source), totals in sorted(by_day.items()):
        row = [day, source, *(str(totals[name]) for name in COLUMNS)]
        lines.append("  ".join(value.ljust(width) for value, width in zip(row, widths)))
    if by_hour:
        lines.append("")
        lines.append("Busiest hours (requests + sign-ins):")
        for hour, count in by_hour.most_common(TOP_HOURS):
            lines.append(f"  {hour.replace('T', ' ')}:00  {count}")
    return "\n".join(lines)


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LOG
    if not path.exists():
        print(f"No usage log at {path}")
        return 1
    print(format_report(*summarize(load_records(path))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
