#!/usr/bin/env python3
"""Rule, physics, statistical and hybrid detectors evaluated on controlled synthetic faults.

Every threshold is either fixed in advance or learned from the training period; the held-out
test window is used for scoring only.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import RobustScaler
from sklearn.metrics import precision_score, recall_score, f1_score, average_precision_score

PF_PV = 0.99; PF_GRID = 0.98; ETA_BAT = 0.95
FEATURES = ['PV Power', 'Wind Power', 'Building Load', 'Grid Power', 'Battery Power', 'Battery SOC',
            'PV Inverter AC Output', 'PV Inverter DC Input', 'PV DC Voltage', 'PV DC Current',
            'PV Inverter AC Voltage LL', 'PV Inverter AC Current', 'Grid Voltage LL', 'Grid Current',
            'Battery Voltage', 'Battery Current', 'Curtailed Power']
# residual key: (plain-language check, unit, channels an operator should compare)
RESIDUALS = {
    'power_balance_kw': ('Power-flow balance (sources vs uses)', 'kW',
                         ['PV Inverter AC Output', 'Wind Power', 'Grid Power', 'Building Load', 'Battery Power', 'Curtailed Power']),
    'pv_dc_kw': ('PV DC power vs DC voltage x current', 'kW', ['PV Inverter DC Input', 'PV DC Voltage', 'PV DC Current']),
    'pv_ac_kw': ('PV AC power vs AC voltage x current', 'kW', ['PV Inverter AC Output', 'PV Inverter AC Voltage LL', 'PV Inverter AC Current']),
    'grid_kw': ('Grid power vs grid voltage x current', 'kW', ['Grid Power', 'Grid Voltage LL', 'Grid Current']),
    'battery_current_a': ('Battery current vs battery power', 'A', ['Battery Power', 'Battery Current', 'Battery Voltage']),
    'pv_source_vs_inverter_kw': ('PV meter vs PV inverter output', 'kW', ['PV Power', 'PV Inverter AC Output']),
}
# Physics limits = 99.9th percentile of the training-year residual + 20% margin. The floor only
# ignores floating-point rounding when the data are noise-free.
THRESHOLD_QUANTILE = 0.999
THRESHOLD_MARGIN = 1.2
THRESHOLD_FLOOR = 0.05
# Fixed limits used by v0.1; kept to show why they fail once meters have realistic error.
FIXED_THRESHOLDS = {k: (5.0 if k == 'battery_current_a' else 2.0) for k in RESIDUALS}
# A spike is a jump larger than this that reverses on the next sample. A step that stays
# (normal battery/grid dispatch) is not a spike.
SPIKE_STEP = {'PV Power': 180, 'Wind Power': 60, 'Building Load': 80, 'Grid Power': 160,
              'Battery Power': 130, 'Battery SOC': 120, 'Grid Current': 240, 'Battery Current': 420}
FROZEN_HOURS = 4
FROZEN_CHANNELS = ['PV Power', 'Building Load', 'Grid Power', 'Battery Power', 'Grid Current']
# Several core channels moving together suggests a real operating change rather than one bad sensor.
COHERENT_STEP = {'PV Power': 100, 'Wind Power': 30, 'Building Load': 60, 'Grid Power': 100, 'Battery Power': 50}
RULE_COLUMNS = ['rule_missing', 'rule_spike', 'rule_frozen']


def physics_pairs(df: pd.DataFrame) -> dict[str, tuple[pd.Series, pd.Series]]:
    """Each check compares a reported value (first) with what related channels imply (second)."""
    bat_p, bat_v = df['Battery Power'], df['Battery Voltage']
    expected_bat_i = pd.Series(np.where(bat_p >= 0, bat_p * 1000 * ETA_BAT / bat_v, bat_p * 1000 / (ETA_BAT * bat_v)), index=df.index)
    return {
        'power_balance_kw': (df['PV Inverter AC Output'] + df['Wind Power'] + df['Grid Power'],
                             df['Building Load'] + bat_p + df['Curtailed Power']),
        'pv_dc_kw': (df['PV Inverter DC Input'], df['PV DC Voltage'] * df['PV DC Current'] / 1000),
        'pv_ac_kw': (df['PV Inverter AC Output'], np.sqrt(3) * df['PV Inverter AC Voltage LL'] * df['PV Inverter AC Current'] * PF_PV / 1000),
        'grid_kw': (df['Grid Power'], np.sqrt(3) * df['Grid Voltage LL'] * df['Grid Current'] * PF_GRID / 1000),
        'battery_current_a': (df['Battery Current'], expected_bat_i),
        'pv_source_vs_inverter_kw': (df['PV Power'], df['PV Inverter AC Output']),
    }


def residuals(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({k: a - b for k, (a, b) in physics_pairs(df).items()}, index=df.index)


def calibrate_thresholds(train: pd.DataFrame) -> dict[str, float]:
    r = residuals(train).abs()
    return {k: max(THRESHOLD_FLOOR, float(r[k].quantile(THRESHOLD_QUANTILE)) * THRESHOLD_MARGIN) for k in RESIDUALS}


def rule_checks(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Per-channel data-quality checks: missing, spike-and-return, frozen non-zero value."""
    missing = df[FEATURES].isna()
    spike = pd.DataFrame(False, index=df.index, columns=list(SPIKE_STEP))
    for c, thr in SPIKE_STEP.items():
        d = df[c].diff()
        nxt = d.shift(-1)  # needs the next sample, so a spike is confirmed one hour late
        spike[c] = (d.abs() > thr) & (nxt.abs() > thr / 2) & (np.sign(nxt) == -np.sign(d))
    frozen = pd.DataFrame(False, index=df.index, columns=FROZEN_CHANNELS)
    for c in FROZEN_CHANNELS:
        repeats = df[c].diff().eq(0).astype(int).rolling(FROZEN_HOURS - 1, min_periods=FROZEN_HOURS - 1).sum()
        frozen[c] = repeats.eq(FROZEN_HOURS - 1) & df[c].abs().gt(10)
    return {'missing': missing, 'spike': spike, 'frozen': frozen}


def detect(df: pd.DataFrame, thresholds: dict[str, float]):
    """Selected detector: any data-quality rule OR any physics residual above its limit."""
    res = residuals(df)
    rules = rule_checks(df)
    phys = pd.DataFrame({k: res[k].abs() > thresholds[k] for k in RESIDUALS})
    out = pd.DataFrame(index=df.index)
    for name in ['missing', 'spike', 'frozen']:
        out[f'rule_{name}'] = rules[name].any(axis=1)
    out['alert_rules'] = out[RULE_COLUMNS].any(axis=1)
    out['alert_physics'] = phys.any(axis=1)
    out['alert_rules_physics'] = out['alert_rules'] | out['alert_physics']
    return out, res, rules, phys


def explain(df: pd.DataFrame, det: pd.DataFrame, res: pd.DataFrame, rules: dict, phys: pd.DataFrame,
            thresholds: dict[str, float]) -> pd.DataFrame:
    """Plain-language reason, interpretation and a transparent (uncalibrated) evidence score."""
    core = [c for c in COHERENT_STEP if c in df]
    coherent = pd.concat([df[c].diff().abs() > COHERENT_STEP[c] for c in core], axis=1).sum(axis=1).ge(2)
    rows = []
    for i in df.index:
        if not det.at[i, 'alert_rules_physics']:
            rows.append(('', 'No integrity conflict detected', 'No detector evidence', 0.10,
                         'The selected checks found no inconsistency. This does not prove the reading is correct.',
                         'No action; keep under normal monitoring.', 'NO_ALERT'))
            continue
        parts, checks = [], []
        gone = [c for c in FEATURES if rules['missing'].at[i, c]]
        if gone:
            checks.append('missing')
            parts.append('no reading from ' + ', '.join(gone))
        for c in SPIKE_STEP:
            if rules['spike'].at[i, c]:
                checks.append(f'spike:{c}')
                parts.append(f'{c} jumped by {df[c].diff().at[i]:+.0f} and reversed on the next sample')
        for c in FROZEN_CHANNELS:
            if rules['frozen'].at[i, c]:
                checks.append(f'frozen:{c}')
                parts.append(f'{c} repeated exactly {df.at[i, c]:.1f} for {FROZEN_HOURS}+ hours')
        ratio = 0.0
        for k, (label, unit, _) in RESIDUALS.items():
            if phys.at[i, k]:
                checks.append(k)
                ratio = max(ratio, abs(res.at[i, k]) / thresholds[k])
                parts.append(f'{label} off by {abs(res.at[i, k]):.1f} {unit} (limit {thresholds[k]:.1f} {unit})')
        if gone:
            row = ('Telemetry gap', 'Reading unavailable', 0.90,
                   'Check the logger / communication link of the listed device; do not fill the gap silently.')
        elif ratio:
            row = ('Likely telemetry / data inconsistency',
                   'Strong cross-signal mismatch' if ratio >= 3 else 'Cross-signal mismatch',
                   round(min(0.95, 0.70 + 0.05 * (ratio - 1)), 2),
                   'Compare the flagged channel with the related channels listed and with the source record; do not auto-correct.')
        elif coherent.at[i]:
            row = ('Potential operating event - verify context', 'Coherent multi-signal change', 0.45,
                   'Several power channels moved together. Check dispatch, weather and operator logs before calling it a sensor fault.')
        else:
            row = ('Possible data-quality issue', 'Pattern rule only', 0.60,
                   'Check adjacent readings for a repeated, delayed or abrupt value and ask an operator to confirm.')
        text = '; '.join(parts)
        rows.append((';'.join(checks), row[0], row[1], row[2], text[:1].upper() + text[1:] + '.', row[3], 'PENDING_REVIEW'))
    return pd.DataFrame(rows, index=df.index, columns=['checks_fired', 'interpretation', 'evidence_label', 'evidence_score',
                                                       'explanation', 'recommended_action', 'review_status'])


def isolation_forest(train: pd.DataFrame, *frames: pd.DataFrame):
    """Statistical baseline fitted only on the training period. Returns scores per frame and a threshold."""
    pipe = make_pipeline(SimpleImputer(strategy='median'), RobustScaler(),
                         IsolationForest(n_estimators=160, contamination=0.02, random_state=20261015, n_jobs=-1))
    pipe.fit(train[FEATURES])
    scores = [-pipe.score_samples(f[FEATURES]) for f in frames]
    # Alert threshold: 98th percentile of the score over the most recent 1,000 training hours.
    threshold = float(np.quantile(-pipe.score_samples(train.iloc[-1000:][FEATURES]), 0.98))
    return scores, threshold


def operator_log(df: pd.DataFrame, det: pd.DataFrame, res: pd.DataFrame, expl: pd.DataFrame) -> pd.DataFrame:
    log = pd.DataFrame({'Timestamp': df['Timestamp']})
    if 'Building Context (synthetic)' in df:
        log['building_context_synthetic'] = df['Building Context (synthetic)'].astype(str)
    for c in RULE_COLUMNS + ['alert_rules', 'alert_physics', 'alert_rules_physics']:
        log[c] = det[c].astype(int)
    for k in RESIDUALS:
        log[f'residual_{k}'] = res[k].round(3)
    return pd.concat([log, expl], axis=1)


def metrics(name, y, pred, score=None):
    y = np.asarray(y, dtype=int); pred = np.asarray(pred, dtype=int)
    return {'detector': name, 'precision': precision_score(y, pred, zero_division=0),
            'recall': recall_score(y, pred, zero_division=0), 'f1': f1_score(y, pred, zero_division=0),
            'average_precision': average_precision_score(y, score if score is not None else pred),
            'tp': int(((y == 1) & (pred == 1)).sum()), 'fp': int(((y == 0) & (pred == 1)).sum()),
            'fn': int(((y == 1) & (pred == 0)).sum()), 'tn': int(((y == 0) & (pred == 0)).sum())}


def event_results(faulted: pd.DataFrame, manifest: pd.DataFrame, pred: pd.Series) -> pd.DataFrame:
    out = []
    for _, ev in manifest.iterrows():
        rows = faulted.index[faulted['fault_event_id'].eq(ev.event_id)]
        hits = rows[pred.loc[rows].to_numpy(dtype=bool)]
        out.append({'event_id': ev.event_id, 'fault_type': ev.fault_type, 'severity': ev.severity,
                    'altered_rows': len(rows), 'flagged_rows': len(hits),
                    'detected': bool(len(hits)), 'fully_detected': len(rows) > 0 and len(hits) == len(rows),
                    'hours_to_first_flag': int(hits[0] - rows[0]) if len(hits) else None})
    return pd.DataFrame(out)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--data', type=Path, default=Path('data/measured_telemetry_1y.csv'))
    p.add_argument('--clean-test', type=Path, default=Path('outputs/clean_test.csv'))
    p.add_argument('--faulted-test', type=Path, default=Path('outputs/perturbed_test.csv'))
    p.add_argument('--manifest', type=Path, default=Path('outputs/fault_manifest.csv'))
    p.add_argument('--outdir', type=Path, default=Path('outputs'))
    a = p.parse_args(); a.outdir.mkdir(parents=True, exist_ok=True)
    full = pd.read_csv(a.data, parse_dates=['Timestamp'])
    clean = pd.read_csv(a.clean_test, parse_dates=['Timestamp'])
    faulted = pd.read_csv(a.faulted_test, parse_dates=['Timestamp'], keep_default_na=True)
    faulted['fault_event_id'] = faulted['fault_event_id'].fillna('')
    manifest = pd.read_csv(a.manifest)
    # Training = every hour before the 60-day test window (7,344 of 8,784 rows, about 84%).
    train = full[full['Timestamp'] < clean['Timestamp'].min()].copy()
    thresholds = calibrate_thresholds(train)
    det_c, res_c, rules_c, phys_c = detect(clean, thresholds)
    det_f, res_f, rules_f, phys_f = detect(faulted, thresholds)
    (score_c, score_f), if_threshold = isolation_forest(train, clean, faulted)
    det_c['alert_iforest'] = score_c > if_threshold
    det_f['alert_iforest'] = score_f > if_threshold
    for d in (det_c, det_f):
        d['alert_full_hybrid'] = d['alert_rules_physics'] | d['alert_iforest']

    # Natural telemetry gaps are real data issues but not injected faults: they are scored
    # separately so they neither inflate recall nor count as false alarms.
    natural_gap = clean[FEATURES].isna().any(axis=1)
    scored = ~natural_gap
    y = faulted['is_fault'].fillna(0).astype(int)
    detectors = [('Rules only', 'alert_rules', None), ('Physical checks only', 'alert_physics', None),
                 ('Rules + physics (selected)', 'alert_rules_physics', None),
                 ('Isolation Forest', 'alert_iforest', score_f),
                 ('Full hybrid (rules + physics + Isolation Forest)', 'alert_full_hybrid', None)]
    table = [metrics(name, y[scored], det_f.loc[scored, key], None if s is None else s[scored.to_numpy()])
             for name, key, s in detectors]
    metrics_df = pd.DataFrame(table)
    metrics_df.to_csv(a.outdir / 'evaluation_metrics.csv', index=False)

    untouched = []
    for name, key, _ in detectors:
        alerts = det_c[key]
        untouched.append({'detector': name, 'untouched_test_rows': int(scored.sum()),
                          'alarm_rows': int(alerts[scored].sum()),
                          'alarm_rate_pct': 100 * float(alerts[scored].mean()),
                          'natural_gap_rows': int(natural_gap.sum()),
                          'natural_gap_rows_flagged': int(alerts[natural_gap].sum()),
                          'interpretation': 'alert rate on the unmodified window (natural gaps excluded); not a verified false-positive rate'})
    pd.DataFrame(untouched).to_csv(a.outdir / 'untouched_test_alarm_rates.csv', index=False)

    expl_f = explain(faulted, det_f, res_f, rules_f, phys_f, thresholds)
    expl_c = explain(clean, det_c, res_c, rules_c, phys_c, thresholds)
    log_f = operator_log(faulted, det_f, res_f, expl_f)
    log_c = operator_log(clean, det_c, res_c, expl_c)
    for log, det in ((log_f, det_f), (log_c, det_c)):
        log.insert(log.columns.get_loc('alert_rules_physics') + 1, 'alert_isolation_forest', det['alert_iforest'].astype(int))
    # Evaluation-only file keeps ground truth; operator-facing files never contain it.
    evaluation = log_f.copy()
    evaluation.insert(1, 'is_fault', y)
    evaluation.insert(2, 'fault_type', faulted['fault_type'])
    evaluation.insert(3, 'fault_event_id', faulted['fault_event_id'])
    evaluation.insert(4, 'natural_gap', natural_gap.astype(int))
    evaluation.to_csv(a.outdir / 'evaluation_predictions.csv', index=False)
    log_f.to_csv(a.outdir / 'alert_log.csv', index=False)
    log_c.to_csv(a.outdir / 'baseline_alert_log.csv', index=False)
    log_f[log_f['alert_rules_physics'] == 1].to_csv(a.outdir / 'review_queue.csv', index=False)

    events = event_results(faulted, manifest, det_f['alert_rules_physics'])
    events.to_csv(a.outdir / 'event_level_results.csv', index=False)
    by_fault = []
    for ft, group in evaluation[evaluation.is_fault == 1].groupby('fault_type'):
        ev = events[events.fault_type == ft]
        by_fault.append({'fault_type': ft, 'events': len(ev), 'affected_rows': len(group),
                         'rules_recall': float(group['alert_rules'].mean()),
                         'physics_recall': float(group['alert_physics'].mean()),
                         'hybrid_recall': float(group['alert_rules_physics'].mean()),
                         'events_detected': int(ev.detected.sum())})
    pd.DataFrame(by_fault).to_csv(a.outdir / 'fault_type_recall.csv', index=False)

    train_scored = ~train[FEATURES].isna().any(axis=1)
    train_alert_rate = 100 * float(detect(train, thresholds)[0].loc[train_scored, 'alert_rules_physics'].mean())
    summary = {'test_period_start': str(clean.Timestamp.min()), 'test_period_end': str(clean.Timestamp.max()),
               'training_rows': len(train), 'test_rows': len(clean), 'injected_events': int(len(manifest)),
               'training_alert_rate_pct': train_alert_rate,
               'labelled_fault_rows': int(y.sum()), 'natural_gap_rows_in_test': int(natural_gap.sum()),
               'physics_thresholds': thresholds, 'isolation_forest_threshold': if_threshold,
               'events_detected': int(events.detected.sum()), 'events_fully_detected': int(events.fully_detected.sum()),
               'metrics': table, 'untouched_test_alarm_rates': untouched,
               'notes': ['All injected faults are synthetic and generated for this experiment.',
                         'Physics limits are learned from the training period only (99.9th percentile + 20%).',
                         'Untouched-window alert rate is not a verified false-positive rate: the simulation has no independent fault labels.',
                         'This evaluates one synthetic simulation with modelled meter error, not a real microgrid.']}
    (a.outdir / 'evaluation_summary.json').write_text(json.dumps(summary, indent=2, default=str))
    print('Physics thresholds:', {k: round(v, 2) for k, v in thresholds.items()})
    print(metrics_df.to_string(index=False, float_format=lambda x: f'{x:.3f}'))
    print('\nUntouched test alert rates:')
    print(pd.DataFrame(untouched).drop(columns='interpretation').to_string(index=False, float_format=lambda x: f'{x:.3f}'))
    print(f'\nEvents detected: {int(events.detected.sum())}/{len(events)} (fully: {int(events.fully_detected.sum())})')


if __name__ == '__main__':
    main()
