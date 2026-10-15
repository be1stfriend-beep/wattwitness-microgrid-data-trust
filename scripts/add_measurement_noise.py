#!/usr/bin/env python3
"""Turn the ideal simulated state into imperfect *measured* telemetry.

The ideal dataset satisfies every power/voltage/current equation exactly, which would make
physical-consistency checks trivially perfect. Real telemetry is not like that: meters have
an accuracy class, a finite resolution, and data loggers occasionally drop readings. This
step adds those imperfections with a fixed seed so the experiment stays reproducible.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd

SEED = 7203
# channel: (relative 1-sigma error, absolute 1-sigma floor, reporting resolution)
# Relative errors follow typical class 0.5 power meters and 0.2% voltage transducers.
METERS = {
    'PV Power': (0.005, 0.10, 0.1),
    'Wind Power': (0.005, 0.10, 0.1),
    'Building Load': (0.005, 0.10, 0.1),
    'Grid Power': (0.005, 0.10, 0.1),
    'Battery Power': (0.005, 0.10, 0.1),
    'Battery SOC': (0.003, 0.50, 0.1),
    'Curtailed Power': (0.010, 0.10, 0.1),
    'PV Inverter AC Output': (0.005, 0.10, 0.1),
    'PV Inverter DC Input': (0.005, 0.10, 0.1),
    'PV DC Voltage': (0.002, 0.20, 0.1),
    'PV DC Current': (0.005, 0.20, 0.1),
    'PV Inverter AC Voltage LL': (0.002, 0.20, 0.1),
    'PV Inverter AC Current': (0.005, 0.20, 0.1),
    'Grid Voltage LL': (0.002, 0.20, 0.1),
    'Grid Current': (0.005, 0.20, 0.1),
    'Battery Voltage': (0.002, 0.20, 0.1),
    'Battery Current': (0.005, 0.20, 0.1),
}
SIGNED = {'Battery Power', 'Battery Current'}
# Devices that report together drop out together.
DROPOUT_GROUPS = {
    'battery management system': ['Battery Power', 'Battery SOC', 'Battery Voltage', 'Battery Current'],
    'grid meter': ['Grid Power', 'Grid Voltage LL', 'Grid Current'],
    'PV inverter': ['PV Inverter AC Output', 'PV Inverter DC Input', 'PV DC Voltage', 'PV DC Current',
                    'PV Inverter AC Voltage LL', 'PV Inverter AC Current'],
    'building meter': ['Building Load'],
    'whole data logger': list(METERS),
}
DROPOUT_START_PROBABILITY = 0.003  # per hour; roughly two to three outages per month
IDEAL_RESIDUAL_COLUMNS = ['Power Balance Residual', 'PV DC Power Consistency Residual',
                          'PV AC Power Consistency Residual', 'Grid Power Consistency Residual']


def add_measurement_effects(ideal: pd.DataFrame, noise_scale: float = 1.0, dropouts: bool = True,
                            seed: int = SEED) -> tuple[pd.DataFrame, list[dict]]:
    """Return measured telemetry and the list of natural telemetry gaps that were created.

    noise_scale multiplies every meter error (0 = noise-free, 1 = the meter spec above).
    A channel whose true value is exactly zero (device off/idle) still reports zero.
    """
    rng = np.random.default_rng(seed)
    out = ideal.drop(columns=IDEAL_RESIDUAL_COLUMNS, errors='ignore').copy()
    for col, (rel, floor, step) in METERS.items():
        true = out[col].to_numpy(dtype=float)
        sigma = noise_scale * np.hypot(rel * np.abs(true), floor)
        measured = true + rng.normal(0.0, 1.0, len(true)) * sigma
        measured = np.where(true == 0, 0.0, measured)
        if col not in SIGNED:
            measured = np.clip(measured, 0.0, None)
        out[col] = np.round(measured / step) * step
    gaps = []
    if dropouts:
        groups = list(DROPOUT_GROUPS)
        i = 0
        while i < len(out):
            if rng.random() < DROPOUT_START_PROBABILITY:
                group = groups[int(rng.integers(len(groups)))]
                duration = int(rng.integers(1, 4))
                end = min(len(out), i + duration) - 1
                out.loc[i:end, DROPOUT_GROUPS[group]] = np.nan
                gaps.append({'start_index': i, 'end_index': end, 'start_time': str(out.loc[i, 'Timestamp']),
                             'duration_hours': end - i + 1, 'device': group})
                i = end + 2
            else:
                i += 1
    return out, gaps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', type=Path, default=Path('data/simulated_microgrid_1y.csv'))
    ap.add_argument('--output', type=Path, default=Path('data/measured_telemetry_1y.csv'))
    ap.add_argument('--summary', type=Path, default=Path('outputs/measurement_summary.json'))
    ap.add_argument('--seed', type=int, default=SEED)
    a = ap.parse_args()
    ideal = pd.read_csv(a.input, parse_dates=['Timestamp'])
    measured, gaps = add_measurement_effects(ideal, seed=a.seed)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.summary.parent.mkdir(parents=True, exist_ok=True)
    measured.to_csv(a.output, index=False, float_format='%.1f')
    summary = {
        'seed': a.seed,
        'rows': int(len(measured)),
        'meter_model': {c: {'relative_sigma': r, 'absolute_sigma': f, 'resolution': s} for c, (r, f, s) in METERS.items()},
        'dropout_start_probability_per_hour': DROPOUT_START_PROBABILITY,
        'natural_gap_events': len(gaps),
        'rows_with_any_missing_value': int(measured[list(METERS)].isna().any(axis=1).sum()),
        'missing_cells': int(measured[list(METERS)].isna().sum().sum()),
        'gaps': gaps,
    }
    a.summary.write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k not in ('meter_model', 'gaps')}, indent=2))


if __name__ == '__main__':
    main()
