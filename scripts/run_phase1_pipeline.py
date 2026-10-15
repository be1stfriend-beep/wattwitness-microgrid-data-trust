#!/usr/bin/env python3
"""Recreate the Phase 1 evaluation, figures and reports from the included ideal dataset."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
S = ROOT / 'scripts'
commands = [
    [sys.executable, str(S / 'add_measurement_noise.py'), '--input', str(ROOT / 'data/simulated_microgrid_1y.csv'),
     '--output', str(ROOT / 'data/measured_telemetry_1y.csv'), '--summary', str(ROOT / 'outputs/measurement_summary.json')],
    [sys.executable, str(S / 'inject_faults.py'), '--input', str(ROOT / 'data/measured_telemetry_1y.csv'),
     '--output', str(ROOT / 'outputs/perturbed_test.csv'), '--clean-output', str(ROOT / 'outputs/clean_test.csv'),
     '--manifest', str(ROOT / 'outputs/fault_manifest.csv')],
    [sys.executable, str(S / 'detect_evaluate.py'), '--data', str(ROOT / 'data/measured_telemetry_1y.csv'),
     '--clean-test', str(ROOT / 'outputs/clean_test.csv'), '--faulted-test', str(ROOT / 'outputs/perturbed_test.csv'),
     '--manifest', str(ROOT / 'outputs/fault_manifest.csv'), '--outdir', str(ROOT / 'outputs')],
    [sys.executable, str(S / 'noise_robustness.py')],
    [sys.executable, str(S / 'make_figures.py')],
]
if '--with-reports' in sys.argv:
    commands += [[sys.executable, str(S / 'create_report.py')], [sys.executable, str(S / 'create_proposal.py')]]
for i, cmd in enumerate(commands, 1):
    print(f'\n[{i}/{len(commands)}] {Path(cmd[1]).name}', flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)
print('\nPipeline completed from the included ideal dataset; see README for rebuilding it from a local base export.')
