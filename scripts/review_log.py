"""Append-only operator review log (local CSV demo audit trail).

Existing rows are never rewritten. A file whose header does not match is moved aside as a
backup before a new log is started, so a damaged or older log is never silently lost.
"""
from __future__ import annotations
import csv
from datetime import datetime
from pathlib import Path
import pandas as pd

REVIEW_COLUMNS = ['decision_timestamp', 'scenario', 'event_timestamp', 'reviewer', 'decision', 'notes',
                  'interpretation', 'evidence_score', 'explanation', 'suggested_check']


def read_decisions(path: Path) -> pd.DataFrame:
    """Read the log. Errors are raised to the caller, never turned into an empty table."""
    if not path.exists():
        return pd.DataFrame(columns=REVIEW_COLUMNS)
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def append_decision(path: Path, record: dict) -> Path | None:
    """Append one decision. Returns the backup path if an incompatible log had to be moved aside."""
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if path.exists():
        with open(path, newline='', encoding='utf-8') as f:
            header = next(csv.reader(f), [])
        if header != REVIEW_COLUMNS:
            backup = path.with_name(f'{path.stem}.backup-{datetime.now():%Y%m%d-%H%M%S}{path.suffix}')
            path.rename(backup)
    new_file = not path.exists()
    with open(path, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=REVIEW_COLUMNS)
        if new_file:
            writer.writeheader()
        writer.writerow({c: record.get(c, '') for c in REVIEW_COLUMNS})
    return backup


def latest_decisions(log: pd.DataFrame) -> dict[tuple[str, str], str]:
    """(scenario, event_timestamp) -> most recent decision. Scenario is part of the key so a
    decision on the fault replay never marks the same hour as reviewed in the clean window."""
    if log.empty:
        return {}
    log = log.sort_values('decision_timestamp')
    return {(r.scenario, r.event_timestamp): r.decision for r in log.itertuples()}
