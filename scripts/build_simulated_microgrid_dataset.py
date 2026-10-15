#!/usr/bin/env python3
"""Build a reproducible one-year simulation-based simulated microgrid dataset.

PV and wind time series are preserved from the supplied export. Building load,
battery/grid dispatch, and the added electrical channels are simulation-derived.
No source measurements are overwritten.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd

START = pd.Timestamp('2023-06-01 00:00:00')
END = pd.Timestamp('2024-05-31 23:00:00')
SEED = 20261015


def make_variable_building_load(timestamps: pd.Series, source_load: pd.Series, seed: int = SEED) -> tuple[np.ndarray, np.ndarray]:
    """Use the original daily shape as a template, then introduce daily/hourly variation.

    This is a synthetic building-load scenario; it is not measured building consumption.
    """
    rng = np.random.default_rng(seed)
    hours = pd.DatetimeIndex(timestamps).hour
    # Robust typical daily shape from the selected year.
    template = pd.DataFrame({'hour': hours, 'load': source_load.to_numpy()}).groupby('hour')['load'].median()
    base = template.reindex(range(24)).interpolate().to_numpy(dtype=float)
    out = np.zeros(len(timestamps), dtype=float)
    context = np.full(len(timestamps), 'regular building operation (synthetic context)', dtype=object)
    idx = pd.DatetimeIndex(timestamps)
    day_ids = idx.normalize().unique()
    # Illustrative seasonality for a commercial/campus building; clearly synthetic.
    seasonal_by_month = {1:1.06, 2:1.05, 3:1.00, 4:0.96, 5:0.98, 6:1.04,
                         7:1.10, 8:1.08, 9:1.03, 10:0.99, 11:0.98, 12:1.02}
    for day in day_ids:
        positions = np.flatnonzero(idx.normalize() == day)
        hrs = idx[positions].hour
        weekday_factor = 1.0 if day.dayofweek < 5 else 0.84
        seasonal = seasonal_by_month[int(day.month)]
        day_factor = float(np.clip(rng.lognormal(mean=-(0.13**2)/2, sigma=0.13), 0.72, 1.32))
        # Correlated hourly variation, not independent white noise.
        noise = np.zeros(len(positions), dtype=float)
        for j in range(len(noise)):
            noise[j] = (0.58 * noise[j-1] if j else 0.0) + rng.normal(0, 0.045)
        values = base[hrs] * weekday_factor * seasonal * day_factor * (1 + noise)
        day_context = 'weekday occupancy pattern' if day.dayofweek < 5 else 'weekend reduced-occupancy pattern'
        if int(day.month) in (6, 7, 8): day_context += '; summer cooling-season assumption'
        elif int(day.month) in (12, 1, 2): day_context += '; winter heating-season assumption'
        context[positions] = day_context + ' (synthetic context, not measured)'
        # Occasional non-repeating operating events (e.g., cleaning, deliveries, events).
        if rng.random() < 0.10:
            start_hour = int(rng.integers(7, 19))
            duration = int(rng.integers(1, 5))
            event_multiplier = float(rng.uniform(1.08, 1.28))
            mask = (hrs >= start_hour) & (hrs < min(24, start_hour + duration))
            values[mask] *= event_multiplier
            context[positions[mask]] = 'scheduled high-demand building activity (synthetic context, not measured)'
        out[positions] = values
    return np.round(np.clip(out, 35.0, 320.0), 2), context


def dispatch_microgrid(pv_kw: np.ndarray, wind_kw: np.ndarray, load_kw: np.ndarray,
                       initial_energy_kwh: float = 100.0, min_energy_kwh: float = 100.0,
                       max_energy_kwh: float = 500.0, max_battery_kw: float = 100.0,
                       charge_efficiency: float = 0.95) -> tuple[np.ndarray, ...]:
    """Hourly dispatch. Battery power is positive when charging and negative when discharging.

    Import from grid is allowed; export is disabled. Renewable surplus remaining when the
    battery cannot accept more energy is recorded as curtailment.
    """
    n = len(load_kw)
    bat_p = np.zeros(n); grid = np.zeros(n); soc = np.zeros(n); curtailed = np.zeros(n)
    energy = float(np.clip(initial_energy_kwh, min_energy_kwh, max_energy_kwh))
    eta = charge_efficiency
    for i in range(n):
        renewable = max(0.0, float(pv_kw[i])) + max(0.0, float(wind_kw[i]))
        load = max(0.0, float(load_kw[i]))
        surplus = renewable - load
        if surplus >= 0:
            charge = min(surplus, max_battery_kw, max(0.0, max_energy_kwh - energy) / eta)
            energy += charge * eta
            bat_p[i] = charge
            curtailed[i] = max(0.0, surplus - charge)
            grid[i] = 0.0
        else:
            deficit = -surplus
            discharge = min(deficit, max_battery_kw, max(0.0, energy - min_energy_kwh) * eta)
            energy -= discharge / eta
            bat_p[i] = -discharge
            grid[i] = max(0.0, deficit - discharge)
            curtailed[i] = 0.0
        energy = float(np.clip(energy, min_energy_kwh, max_energy_kwh))
        soc[i] = energy
    return bat_p, grid, soc, curtailed


def add_derived_electrical_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Add simplified, explicitly synthetic inverter/grid/battery voltage-current channels."""
    out = df.copy()
    pv_ac = out['PV Power'].clip(lower=0).to_numpy(dtype=float)
    wind = out['Wind Power'].clip(lower=0).to_numpy(dtype=float)
    grid_p = out['Grid Power'].clip(lower=0).to_numpy(dtype=float)
    bat_p = out['Battery Power'].to_numpy(dtype=float)
    soc = out['Battery SOC'].to_numpy(dtype=float)
    eta_inv, pf_inv, pf_grid, eta_bat = 0.97, 0.99, 0.98, 0.95
    # PV source power is treated as AC-side output of an inverter in this model.
    pv_dc = pv_ac / eta_inv
    pv_frac = pv_ac / max(float(np.nanmax(pv_ac)), 1.0)
    pv_vdc = np.where(pv_ac > 0.01, 500.0 + 50.0 * np.sqrt(pv_frac), 0.0)
    pv_idc = np.divide(pv_dc * 1000.0, pv_vdc, out=np.zeros_like(pv_dc), where=pv_vdc > 0)
    pv_vll = np.where(pv_ac > 0.01, 400.0, 0.0)
    pv_iac = np.divide(pv_ac * 1000.0, np.sqrt(3.0) * pv_vll * pf_inv,
                       out=np.zeros_like(pv_ac), where=pv_vll > 0)
    # Simplified equivalent grid-source voltage-drop assumption: V_LL = 400 V - 0.02 V/A.
    grid_v = np.full(len(grid_p), 400.0)
    for _ in range(8):
        grid_i = np.divide(grid_p * 1000.0, np.sqrt(3.0) * grid_v * pf_grid,
                           out=np.zeros_like(grid_p), where=grid_v > 0)
        grid_v = np.clip(400.0 - 0.02 * grid_i, 375.0, 400.0)
    grid_i = np.divide(grid_p * 1000.0, np.sqrt(3.0) * grid_v * pf_grid,
                        out=np.zeros_like(grid_p), where=grid_v > 0)
    # A simplified battery pack voltage model maps energy range (100-500 kWh) to 350-420 V.
    bat_v = 350.0 + 70.0 * np.clip((soc - 100.0) / 400.0, 0, 1)
    bat_i = np.where(bat_p >= 0, bat_p * 1000.0 * eta_bat / bat_v,
                     bat_p * 1000.0 / (eta_bat * bat_v))
    out['PV Inverter AC Output'] = pv_ac
    out['PV Inverter DC Input'] = pv_dc
    out['PV DC Voltage'] = pv_vdc
    out['PV DC Current'] = pv_idc
    out['PV Inverter AC Voltage LL'] = pv_vll
    out['PV Inverter AC Current'] = pv_iac
    out['Grid Voltage LL'] = grid_v
    out['Grid Current'] = grid_i
    out['Battery Voltage'] = bat_v
    out['Battery Current'] = bat_i
    out['Power Balance Residual'] = (pv_ac + wind + grid_p - out['Building Load'].to_numpy(dtype=float)
                                       - bat_p - out['Curtailed Power'].to_numpy(dtype=float))
    out['PV DC Power Consistency Residual'] = pv_dc - pv_vdc * pv_idc / 1000.0
    out['PV AC Power Consistency Residual'] = pv_ac - np.sqrt(3.0) * pv_vll * pv_iac * pf_inv / 1000.0
    out['Grid Power Consistency Residual'] = grid_p - np.sqrt(3.0) * grid_v * grid_i * pf_grid / 1000.0
    return out


def build(input_csv: Path, output_csv: Path, summary_path: Path, seed: int = SEED) -> dict:
    raw = pd.read_csv(input_csv)
    required = {'snapshot', 'PV Power', 'Wind Power', 'Grid Power', 'Load', 'Battery SOC', 'Battery Charger'}
    missing = sorted(required - set(raw.columns))
    if missing:
        raise ValueError(f'Input is missing required columns: {missing}')
    raw['snapshot'] = pd.to_datetime(raw['snapshot'], errors='coerce')
    raw = raw.dropna(subset=['snapshot']).sort_values('snapshot')
    # Latest complete 12-month window in the supplied export.
    data = raw[(raw['snapshot'] >= START) & (raw['snapshot'] <= END)].copy()
    data = data.drop_duplicates(subset=['snapshot'], keep='first').sort_values('snapshot').reset_index(drop=True)
    if data.empty:
        raise ValueError(f'No rows found between {START} and {END}')
    if data['snapshot'].duplicated().any():
        raise ValueError('Duplicate timestamps remain after de-duplication')
    dt_hours = data['snapshot'].diff().dropna().dt.total_seconds().div(3600)
    if len(data) != 8784:
        raise ValueError(f'Expected 8784 hourly rows for {START} to {END}, got {len(data)}')
    if not np.allclose(dt_hours, 1.0):
        raise ValueError('Selected period is not a continuous hourly series')
    for c in ['PV Power', 'Wind Power']:
        data[c] = pd.to_numeric(data[c], errors='coerce').fillna(0).clip(lower=0)
    original_load_template = pd.to_numeric(data['Load'], errors='coerce').interpolate().bfill().ffill()
    load, context = make_variable_building_load(data['snapshot'], original_load_template, seed=seed)
    pv = data['PV Power'].to_numpy(dtype=float)
    wind = data['Wind Power'].to_numpy(dtype=float)
    batt_p, grid, soc, curtail = dispatch_microgrid(pv, wind, load)
    built = pd.DataFrame({
        'Timestamp': data['snapshot'],
        'PV Power': pv,
        'Wind Power': wind,
        'Building Load': load,
        'Grid Power': np.round(grid, 6),
        'Battery Power': np.round(batt_p, 6),
        'Battery SOC': np.round(soc, 6),
        'Curtailed Power': np.round(curtail, 6),
        'Source Template Load (reference only)': original_load_template.to_numpy(dtype=float),
        'Building Context (synthetic)': context,
    })
    built = add_derived_electrical_signals(built)
    # Numeric channel units and provenance are explicit in the data dictionary/docs.
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    built.to_csv(output_csv, index=False, float_format='%.6f')
    summary = {
        'dataset_name':'one-year simulated microgrid dataset',
        'period_start':built['Timestamp'].min().isoformat(sep=' '),
        'period_end':built['Timestamp'].max().isoformat(sep=' '),
        'rows':int(len(built)), 'time_step_hours':1,
        'input_rows_in_selected_period':int(len(data)),
        'source_pv_wind_preserved':True,
        'building_load_is_synthetic':True,
        'building_context_is_synthetic':True,
        'scheduled_activity_hours':int((built['Building Context (synthetic)']=='scheduled high-demand building activity (synthetic context, not measured)').sum()),
        'ev_load_used':False,
        'derived_signals_are_synthetic':True,
        'load_min':float(built['Building Load'].min()),
        'load_max':float(built['Building Load'].max()),
        'load_mean':float(built['Building Load'].mean()),
        'load_unique_rounded_2dp':int(built['Building Load'].round(2).nunique()),
        'power_balance_residual_abs_max':float(built['Power Balance Residual'].abs().max()),
        'pv_dc_consistency_residual_abs_max':float(built['PV DC Power Consistency Residual'].abs().max()),
        'pv_ac_consistency_residual_abs_max':float(built['PV AC Power Consistency Residual'].abs().max()),
        'grid_consistency_residual_abs_max':float(built['Grid Power Consistency Residual'].abs().max()),
        'model_assumptions':{
            'source_power_units':'Assumed kW; verify against original PyPSA model',
            'source_pv_power_interpretation':'Treated as PV inverter AC output for this simulation',
            'battery_soc':'Interpreted as usable stored energy range 100-500 kWh based on source field behavior; verify original model',
            'battery_power_limit_kw':100,
            'battery_charge_discharge_efficiency':0.95,
            'pv_inverter_efficiency':0.97,
            'pv_inverter_pf':0.99,
            'grid_pf':0.98,
            'nominal_three_phase_voltage_ll_v':400,
            'grid_model':'Simplified 400 V equivalent source with assumed voltage drop 0.02 V/A; export disabled; excess renewable power curtailed',
            'battery_voltage_model':'Simplified linear 350-420 V relation across 100-500 kWh SOC; synthetic, not equipment-specific',
            'building_load':'Synthetic variable profile based on original hourly load shape; variability by weekday/weekend, month, daily random factor, correlated hourly noise, and intermittent events',
            'wind_series':'Preserved from source export; provenance/measurement-vs-simulation status inherited from source model and must be documented by project owner'
        }
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2))
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', type=Path, default=Path('data/base_simulation_export.csv'))
    ap.add_argument('--output', type=Path, default=Path('data/simulated_microgrid_1y.csv'))
    ap.add_argument('--summary', type=Path, default=Path('outputs/dataset_audit_summary.json'))
    ap.add_argument('--seed', type=int, default=SEED)
    a = ap.parse_args()
    print(json.dumps(build(a.input, a.output, a.summary, a.seed), indent=2))

if __name__ == '__main__': main()
