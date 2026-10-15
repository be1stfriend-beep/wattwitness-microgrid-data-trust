#!/usr/bin/env python3
import json
import sys
from pathlib import Path
import pandas as pd, numpy as np, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from detect_evaluate import residuals  # noqa: E402

OUT = ROOT / 'figures'; OUT.mkdir(exist_ok=True)
INK, AMBER, TEAL, RED, GREY = '#10212E', '#C27C0E', '#0F766E', '#C2410C', '#8A97A3'
plt.rcParams.update({'axes.spines.top': False, 'axes.spines.right': False, 'axes.titleweight': 'bold',
                     'axes.titlesize': 12, 'axes.edgecolor': '#5B6B78', 'font.size': 10})
ideal = pd.read_csv(ROOT / 'data/simulated_microgrid_1y.csv', parse_dates=['Timestamp'])
df = pd.read_csv(ROOT / 'data/measured_telemetry_1y.csv', parse_dates=['Timestamp'])
summary = json.loads((ROOT / 'outputs/evaluation_summary.json').read_text())

# 1: two-week building load
fig, ax = plt.subplots(figsize=(12, 4.4))
ss = ideal.iloc[:24 * 14]
ax.plot(ss.Timestamp, ss['Source Template Load (reference only)'], label='Original repeated-load template', lw=1.4, color=GREY)
ax.plot(ss.Timestamp, ss['Building Load'], label='Variable synthetic building load', lw=1.5, color=INK)
ax.set_title('Building load: original daily template vs variable synthetic profile')
ax.set_ylabel('Power (kW, assumed)'); ax.grid(alpha=.25); ax.legend(ncol=2, frameon=False)
fig.tight_layout(); fig.savefig(OUT / 'building_load_variability_14days.png', dpi=180); plt.close(fig)

# 2: annual smoothed profiles
fig, ax = plt.subplots(figsize=(12, 4.4))
for col, label, color in [('PV Power', 'PV output (base simulation)', AMBER), ('Wind Power', 'Wind output (base simulation)', TEAL),
                          ('Building Load', 'Synthetic building load', INK), ('Grid Power', 'Recomputed grid import', RED)]:
    s = df.set_index('Timestamp')[col].rolling(24 * 14, min_periods=1).mean()
    ax.plot(s.index, s.values, label=label, lw=1.4, color=color)
ax.set_title('Annual microgrid power profiles (14-day rolling mean)'); ax.set_ylabel('Power (kW, assumed)')
ax.grid(alpha=.25); ax.legend(ncol=2, frameon=False)
fig.tight_layout(); fig.savefig(OUT / 'annual_power_profiles_14day_mean.png', dpi=180); plt.close(fig)

# 3: power-balance residual of the measured telemetry against the learned limit
res = residuals(df)['power_balance_kw']
limit = summary['physics_thresholds']['power_balance_kw']
fig, ax = plt.subplots(figsize=(12, 4.2))
ax.plot(df.Timestamp, res, lw=.5, color=INK, label='measured residual (meter error only)')
ax.plot(ideal.Timestamp, residuals(ideal)['power_balance_kw'], lw=1.2, color=TEAL, label='ideal simulation (exactly 0)')
for s in (-1, 1):
    ax.axhline(s * limit, color=AMBER, ls='--', lw=1.3, label=f'learned limit ±{limit:.1f} kW' if s == 1 else None)
ax.set_title('Power-balance residual: ideal simulation vs measured telemetry')
ax.set_ylabel('Residual (kW)'); ax.grid(alpha=.25); ax.legend(frameon=False, ncol=3, loc='upper right')
fig.tight_layout(); fig.savefig(OUT / 'power_balance_residual.png', dpi=180); plt.close(fig)

# 4: detector comparison
m = pd.read_csv(ROOT / 'outputs/evaluation_metrics.csv')
fig, ax = plt.subplots(figsize=(10.5, 5.0)); x = np.arange(len(m)); width = .25
for j, (col, color) in enumerate([('precision', INK), ('recall', AMBER), ('f1', TEAL)]):
    ax.bar(x + (j - 1) * width, m[col], width, label=col.title() if col != 'f1' else 'F1', color=color)
ax.set_xticks(x); ax.set_xticklabels([d.replace(' (', '\n(') for d in m.detector], fontsize=8.5)
ax.set_ylim(0, 1.08); ax.set_ylabel('Score'); ax.set_title('Detection results on controlled synthetic faults (0.5% meter error)')
ax.legend(frameon=False, ncol=3); ax.grid(axis='y', alpha=.25)
fig.tight_layout(); fig.savefig(OUT / 'detector_comparison.png', dpi=180); plt.close(fig)

# 5: fault example (12% grid-current bias)
pred = pd.read_csv(ROOT / 'outputs/evaluation_predictions.csv', parse_dates=['Timestamp'])
manifest = pd.read_csv(ROOT / 'outputs/fault_manifest.csv')
clean = pd.read_csv(ROOT / 'outputs/clean_test.csv', parse_dates=['Timestamp'])
faulted = pd.read_csv(ROOT / 'outputs/perturbed_test.csv', parse_dates=['Timestamp'])
ex = manifest[manifest.fault_type == 'plausible_bias'].iloc[0]
lo, hi = pd.Timestamp(ex.start_time) - pd.Timedelta(hours=8), pd.Timestamp(ex.end_time) + pd.Timedelta(hours=8)
win = lambda d: d[(d.Timestamp >= lo) & (d.Timestamp <= hi)]
fig, axs = plt.subplots(2, 1, figsize=(11, 6), sharex=True, gridspec_kw={'height_ratios': [2.2, 1]})
axs[0].plot(win(clean).Timestamp, win(clean)['Grid Current'], label='clean grid current', lw=1.5, color=GREY, ls='--')
axs[0].plot(win(faulted).Timestamp, win(faulted)['Grid Current'], label='reported (biased) grid current', lw=1.6, color=INK)
axs[0].axvspan(pd.Timestamp(ex.start_time), pd.Timestamp(ex.end_time), color=AMBER, alpha=.15, label='injected window')
axs[0].set_ylabel('Current (A)'); axs[0].legend(frameon=False); axs[0].grid(alpha=.25)
axs[1].step(win(pred).Timestamp, win(pred)['alert_rules_physics'], where='mid', lw=1.6, color=RED, label='rules + physics alert')
axs[1].set_ylabel('Alert'); axs[1].set_ylim(-.1, 1.1); axs[1].set_yticks([0, 1]); axs[1].grid(alpha=.25); axs[1].legend(frameon=False)
fig.suptitle(f'Example {ex.event_id}: {ex.severity}', fontweight='bold')
fig.tight_layout(); fig.savefig(OUT / 'fault_case_grid_current_bias.png', dpi=180); plt.close(fig)

# 6: robustness to meter error
noise = pd.read_csv(ROOT / 'outputs/noise_robustness.csv')
fig, axs = plt.subplots(1, 2, figsize=(11.5, 4.2))
for (label, g), color in zip(noise.groupby('thresholds'), [RED, TEAL]):
    axs[0].plot(g.power_meter_error_pct, g.f1, marker='o', color=color, label=label)
    axs[1].plot(g.power_meter_error_pct, g.clean_window_alert_rate_pct, marker='o', color=color, label=label)
axs[0].set_title('F1 on injected faults'); axs[0].set_ylim(0, 1.02)
axs[1].set_title('Alert rate on clean hours (%)'); axs[1].set_yscale('symlog', linthresh=1)
for a in axs:
    a.set_xlabel('Power / current meter error, 1 sigma (%)'); a.grid(alpha=.25)
axs[0].legend(frameon=False, fontsize=8.5)
fig.tight_layout(); fig.savefig(OUT / 'noise_robustness.png', dpi=180); plt.close(fig)

# 7: architecture
fig, ax = plt.subplots(figsize=(13, 6.6))
ax.set_xlim(0, 13); ax.set_ylim(0, 6.6); ax.axis('off')
ax.set_title('WattWitness — Phase 1 single-node architecture', fontsize=16, fontweight='bold', pad=14, color=INK)


def box(x, y, w, h, title, sub='', fc='#F3F1EC', ec=INK):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.035,rounding_size=0.10', lw=1.4, edgecolor=ec, facecolor=fc))
    ax.text(x + w / 2, y + h * 0.63, title, ha='center', va='center', fontsize=10.2, fontweight='bold', color=INK)
    if sub:
        ax.text(x + w / 2, y + h * 0.30, sub, ha='center', va='center', fontsize=8.6, color='#3E5668')


def arrow(x1, y1, x2, y2):
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1), arrowprops=dict(arrowstyle='-|>', lw=1.3, color='#617A8B'))


box(.3, 4.8, 2.3, 1.05, 'Base simulation', 'PV + wind series')
box(2.95, 4.8, 2.3, 1.05, 'Ideal state', 'synthetic load, dispatch, V/I')
box(5.6, 4.8, 2.3, 1.05, 'Meter model', 'error, resolution, gaps', fc='#FBF0DC', ec=AMBER)
box(8.25, 4.8, 2.0, 1.05, 'Training year', 'learn limits')
box(10.6, 4.8, 2.1, 1.05, 'Test window', '+ injected faults', fc='#FBF0DC', ec=AMBER)
arrow(2.6, 5.32, 2.95, 5.32); arrow(5.25, 5.32, 5.6, 5.32); arrow(7.9, 5.32, 8.25, 5.32); arrow(10.25, 5.32, 10.6, 5.32)
box(.9, 2.85, 2.9, 1.05, 'Data-quality rules', 'missing · spike-and-return · frozen')
box(4.55, 2.85, 2.9, 1.05, 'Physics cross-checks', '6 residuals vs learned limits')
box(8.2, 2.85, 3.2, 1.05, 'Statistical baseline', 'Isolation Forest (comparison only)', fc='#EEF1F4', ec=GREY)
arrow(9.25, 4.8, 6.0, 3.9); arrow(11.6, 4.8, 2.35, 3.9); arrow(11.65, 4.8, 6.4, 3.9); arrow(11.7, 4.8, 9.8, 3.9)
box(2.6, .75, 4.3, 1.15, 'Explained alert', 'checks fired · mismatch vs limit · evidence score', fc='#E3F1EE', ec=TEAL)
box(7.6, .75, 4.0, 1.15, 'Human review', 'confirm · genuine event · escalate · dismiss', fc='#E3F1EE', ec=TEAL)
arrow(2.35, 2.85, 3.9, 1.9); arrow(6.0, 2.85, 5.0, 1.9); arrow(6.9, 1.32, 7.6, 1.32)
ax.text(6.5, .25, 'No automatic correction or equipment control. Goal 4 (cross-node sharing) is a documented design only.',
        ha='center', va='center', fontsize=9, color='#596E7C')
fig.tight_layout(); fig.savefig(OUT / 'architecture.png', dpi=180, bbox_inches='tight'); plt.close(fig)
print('Wrote figures:', *sorted(x.name for x in OUT.glob('*.png')), sep='\n- ')
