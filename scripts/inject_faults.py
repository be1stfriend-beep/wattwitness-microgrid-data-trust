#!/usr/bin/env python3
"""Inject controlled, labelled telemetry faults into a copy of the held-out period."""
from __future__ import annotations
import argparse
from pathlib import Path
import json
import numpy as np
import pandas as pd

SEED = 4152026
SPECS = [
    ('spike', 'Grid Power', 1), ('frozen', 'PV Power', 8), ('gradual_drift', 'Building Load', 24),
    ('missing', 'Battery SOC', 4), ('delayed_signal', 'PV Power', 12), ('plausible_bias', 'Grid Current', 6),
]
START_HOUR = {'spike': 20, 'frozen': 9, 'gradual_drift': 6, 'missing': 1, 'delayed_signal': 8, 'plausible_bias': 20}
# Each round repeats the six fault types; spikes and biases get smaller (gross -> subtle) so the
# test probes the detection limit instead of only obvious cases.
SPIKE_KW = [200.0, 80.0, 40.0]
BIAS_FACTOR = [1.12, 1.08, 1.05]


def inject(df: pd.DataFrame, test_rows: int = 1440, seed: int = SEED):
    clean = df.tail(test_rows).reset_index(drop=True).copy()
    faulted = clean.copy()
    faulted['is_fault'] = 0
    faulted['fault_type'] = 'none'
    faulted['fault_event_id'] = ''
    n = len(faulted)
    # Natural telemetry gaps are already "unknown"; never stack an injected fault on top of one.
    occupied = set(np.flatnonzero(clean.isna().any(axis=1).to_numpy()))
    manifest = []
    for round_i in range(3):
        for type_i, (kind, signal, dur) in enumerate(SPECS):
            base_day = 2 + round_i * 18 + type_i * 2
            start = base_day * 24 + START_HOUR[kind]
            if start + dur >= n:
                start = min(n - dur - 1, int((round_i + 1) * n / 4 + type_i * 13))
            # A frozen PV reading is only meaningful while the panels produce power.
            if kind == 'frozen':
                for k in range(24):
                    cand = min(n - dur - 1, start + k)
                    if 7 <= pd.Timestamp(faulted.loc[cand, 'Timestamp']).hour <= 12 and faulted.loc[cand, 'PV Power'] > 20:
                        start = cand
                        break
            if kind == 'plausible_bias' and not float(faulted.loc[start, 'Grid Current']) >= 5:
                day_start = (start // 24) * 24
                options = [j for j in range(day_start, min(day_start + 24, n - dur)) if faulted.loc[j, 'Grid Current'] > 20]
                if options:
                    start = options[-1]
            while any(j in occupied for j in range(start, start + dur)) and start + dur + 1 < n:
                start += dur + 2
            if start + dur >= n:
                continue
            end = start + dur - 1
            eid = f'F{len(manifest) + 1:02d}'
            original = faulted[signal].copy()
            if kind == 'spike':
                faulted.loc[start, signal] = float(faulted.loc[start, signal]) + SPIKE_KW[round_i]
                severity = f'single-sample upward spike of +{SPIKE_KW[round_i]:.0f} kW'
            elif kind == 'frozen':
                faulted.loc[start:end, signal] = float(faulted.loc[start, signal])
                severity = 'sensor holds one value for 8 hours'
            elif kind == 'gradual_drift':
                anchor = float(faulted.loc[start, signal])
                increments = np.linspace(0.0, max(25.0, abs(anchor) * 0.35), dur)
                faulted.loc[start:end, signal] = faulted.loc[start:end, signal].to_numpy(dtype=float) + increments
                severity = 'linear positive drift reaching 35% of the reading (at least 25 kW)'
            elif kind == 'missing':
                faulted.loc[start:end, signal] = np.nan
                severity = 'four missing hourly values'
            elif kind == 'delayed_signal':
                src = np.maximum(0, np.arange(start, end + 1) - 3)
                faulted.loc[start:end, signal] = original.iloc[src].to_numpy()
                severity = 'PV signal replayed with a 3-hour delay'
            elif kind == 'plausible_bias':
                faulted.loc[start:end, signal] = faulted.loc[start:end, signal].to_numpy(dtype=float) * BIAS_FACTOR[round_i]
                severity = f'grid-current reading increased by {100 * (BIAS_FACTOR[round_i] - 1):.0f}%'
            # Label only rows whose reading really changed. The first hour of a drift (offset 0) or
            # of a frozen sensor (holds the true value) is indistinguishable from clean data.
            window = list(range(start, end + 1))
            altered = [j for j in window if not faulted.at[j, signal] == clean.at[j, signal]]
            faulted.loc[altered, 'is_fault'] = 1
            faulted.loc[altered, 'fault_type'] = kind
            faulted.loc[altered, 'fault_event_id'] = eid
            occupied.update(window)
            manifest.append({'event_id': eid, 'fault_type': kind, 'affected_signal': signal, 'start_index': start,
                             'end_index': end, 'start_time': str(faulted.loc[start, 'Timestamp']),
                             'end_time': str(faulted.loc[end, 'Timestamp']), 'duration_rows': dur,
                             'altered_rows': len(altered), 'severity': severity, 'seed': seed})
    return clean, faulted, pd.DataFrame(manifest)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', type=Path, default=Path('data/measured_telemetry_1y.csv'))
    p.add_argument('--test-rows', type=int, default=1440)
    p.add_argument('--seed', type=int, default=SEED)
    p.add_argument('--output', type=Path, default=Path('outputs/perturbed_test.csv'))
    p.add_argument('--clean-output', type=Path, default=Path('outputs/clean_test.csv'))
    p.add_argument('--manifest', type=Path, default=Path('outputs/fault_manifest.csv'))
    a = p.parse_args()
    df = pd.read_csv(a.input, parse_dates=['Timestamp'])
    clean, faulted, manifest = inject(df, a.test_rows, a.seed)
    for f in [a.output, a.clean_output, a.manifest]:
        f.parent.mkdir(parents=True, exist_ok=True)
    clean.to_csv(a.clean_output, index=False)
    faulted.to_csv(a.output, index=False)
    manifest.to_csv(a.manifest, index=False)
    print(json.dumps({'test_rows': len(clean), 'injected_events': len(manifest), 'fault_rows': int(faulted['is_fault'].sum()),
                      'event_counts': manifest['fault_type'].value_counts().to_dict()}, indent=2))


if __name__ == '__main__':
    main()
