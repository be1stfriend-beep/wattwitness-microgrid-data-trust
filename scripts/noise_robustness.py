#!/usr/bin/env python3
"""How does the selected detector behave as meter error grows?

For each noise level the ideal simulation is re-measured, faults are re-injected with the same
schedule, and the rules + physics detector is scored twice: with the fixed 2 kW / 5 A limits of
v0.1 and with limits recalibrated on that level's training period.
"""
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from add_measurement_noise import add_measurement_effects  # noqa: E402
from inject_faults import inject  # noqa: E402
from detect_evaluate import FEATURES, FIXED_THRESHOLDS, calibrate_thresholds, detect  # noqa: E402
from sklearn.metrics import precision_score, recall_score, f1_score  # noqa: E402

NOISE_SCALES = [0.0, 0.5, 1.0, 2.0, 4.0]  # x the meter spec; 1.0 = 0.5% power / current error


def main():
    ideal = pd.read_csv(ROOT / 'data/simulated_microgrid_1y.csv', parse_dates=['Timestamp'])
    rows = []
    for scale in NOISE_SCALES:
        measured, _ = add_measurement_effects(ideal, noise_scale=scale)
        clean, faulted, _ = inject(measured)
        train = measured.iloc[:-len(clean)]
        scored = ~clean[FEATURES].isna().any(axis=1)
        y = faulted.loc[scored, 'is_fault']
        for label, thr in [('fixed 2 kW / 5 A limits (v0.1)', FIXED_THRESHOLDS),
                           ('limits calibrated on training data', calibrate_thresholds(train))]:
            pred = detect(faulted, thr)[0].loc[scored, 'alert_rules_physics']
            clean_alerts = detect(clean, thr)[0].loc[scored, 'alert_rules_physics']
            rows.append({'noise_scale': scale, 'power_meter_error_pct': 0.5 * scale, 'thresholds': label,
                         'precision': precision_score(y, pred, zero_division=0),
                         'recall': recall_score(y, pred, zero_division=0),
                         'f1': f1_score(y, pred, zero_division=0),
                         'clean_window_alert_rate_pct': 100 * float(np.mean(clean_alerts))})
    out = pd.DataFrame(rows)
    out.to_csv(ROOT / 'outputs/noise_robustness.csv', index=False)
    print(out.to_string(index=False, float_format=lambda x: f'{x:.3f}'))


if __name__ == '__main__':
    main()
