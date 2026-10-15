# WattWitness — Microgrid Data Trust Layer

**Phase 1 prototype for the TSYP14 EnergyMind Tunisia challenge.** WattWitness treats every telemetry reading as testimony and cross-examines it against the physics it must satisfy — power balance, voltage × current × power factor, battery current — and against simple data-quality rules. Disagreements become explained alerts that a human must judge. Nothing is corrected automatically and no equipment is controlled.

> **Data honesty.** One simulated node, hourly, one year. PV and wind come from a supplied simulation export; building load, context labels, battery/grid dispatch and voltage/current/inverter channels are synthetic or derived; meter error and telemetry outages are *modelled*. Results validate the method on controlled faults, not performance on physical equipment.

## Official challenge goals and status

| Official goal | What WattWitness provides | Status |
|---|---|---|
| **1. Anomaly & Bias Detection** | Missing / spike-and-return / frozen rules plus six physics cross-checks whose limits are learned from training data. Six injected fault types at gross → subtle severity. | **Implemented, simulated validation.** Separating genuine events from faulty data still needs trusted context and real labels. |
| **2. Confidence Scores & Explainability** | Each alert names the checks that fired, the size of every mismatch against its limit, an interpretation, a suggested check and a transparent evidence score. | **Implemented; score not calibrated** (heuristic, not a probability). |
| **3. Human-AI Escalation & Governance** | Review queue, four decisions (confirm / likely genuine event / escalate / dismiss), escalation policy, append-only audit log. | **Prototype.** No authentication or secured storage. |
| **4. Shared Learning Across the Noosphere** | [`docs/cross_node_design.md`](docs/cross_node_design.md): what nodes share, what stays local, compatibility checks, provenance, poisoning and privacy risks. | **Design only** — allowed for Phase 1. |

## Results (held-out 60 days, 0.5 % meter error)

| Detector | Precision | Recall | F1 |
|---|---|---|---|
| Rules only | 1.000 | 0.182 | 0.309 |
| Physical checks only | 0.984 | 0.792 | 0.878 |
| **Rules + physics (selected)** | **0.986** | **0.881** | **0.930** |
| Isolation Forest (baseline) | 0.267 | 0.145 | 0.188 |
| Full hybrid (+ Isolation Forest) | 0.684 | 0.887 | 0.773 |

- **Rows:** 140 of 159 altered readings found, 2 false alerts. **Events:** 18 of 18 flagged, 14 on every altered hour. The misses are the first hours of gradual drifts (still inside meter error) and the subtlest 5 % current bias at low current.
- **Clean window:** alerts on 0.21 % of unmodified hours (3 of 1,438), versus 0.25 % on the training period, so the limits were not tuned on the test window. The 2 hours with a natural outage are flagged as telemetry gaps and scored separately.
- **Robustness:** with the fixed 2 kW limits of the first iteration, 0.5 % meter error drops F1 to 0.53 and flags 21.7 % of clean hours. Learned limits keep clean-hour alerts near 0.2 % at every noise level; F1 falls gradually to 0.62 at 2 % error as subtle faults disappear into noise (`outputs/noise_robustness.csv`).

These are results on deliberately injected synthetic faults, not real-world accuracy, and the clean-window alert rate is not a verified false-positive rate.

## Quick start

Tested with Python 3.13 on Windows.

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python scripts/run_phase1_pipeline.py      # meter model -> faults -> detection -> sensitivity -> figures
python -m unittest discover -s tests -v    # 18 checks
python app.py                              # local review app, opens http://127.0.0.1:8501
```

`python scripts/run_phase1_pipeline.py --with-reports` also rebuilds `reports/*.docx`; export them to PDF from Word after updating the table of contents.

The review app needs no extra packages. Each flagged hour opens as a case: a plain-language headline, the reported value against what the other meters imply (with the normal meter-error band), all six cross-checks against their limits, and four one-click decisions (keys 1–4, J/K to move). Decisions are appended to `outputs/operator_review_decisions.csv` (created on first use, never rewritten). *Show answers* reveals where faults were planted; keep it off for a realistic review.

## How the data are built

```
supplied PV/wind series
   -> ideal state: synthetic load, recomputed dispatch, derived V/I     data/simulated_microgrid_1y.csv
   -> meter model: 0.2-0.5 % error, 0.1-unit resolution, 18 outages     data/measured_telemetry_1y.csv
   -> first 7,344 h: learn limits  |  last 1,440 h: inject 18 faults
   -> rules + physics detector -> explained alerts -> human decision
```

The ideal state satisfies every equation exactly, so testing physics checks on it would be circular; detection therefore runs on the measured telemetry. Only readings whose value an injection actually changed are labelled as faults.

The original base export is **not** included. With permission to use it, rebuild the ideal dataset with `python scripts/build_simulated_microgrid_dataset.py --input PATH_TO_EXPORT`.

## Repository layout

| Path | Contents |
|---|---|
| `scripts/add_measurement_noise.py` | Meter model: ideal state → measured telemetry with error, resolution and outages |
| `scripts/inject_faults.py` | 18 labelled faults (6 types × 3 severities) in a copy of the test window |
| `scripts/detect_evaluate.py` | Rules, physics checks with learned limits, Isolation Forest, explanations, metrics |
| `scripts/noise_robustness.py` | Sensitivity of the detector to meter error, fixed vs learned limits |
| `scripts/review_log.py` | Append-only review log (never rewrites or silently drops entries) |
| `scripts/make_figures.py`, `create_report.py`, `create_proposal.py` | Figures and Word documents built from the outputs |
| `app.py`, `ui/index.html` | Local review app: a small standard-library server plus a single-page interface |
| `outputs/` | Fault manifest, test copies, per-row alerts, event-level results, metrics, summaries |
| `reports/` | Phase 1 technical report and project proposal (PDF + DOCX) |
| `docs/` | Architecture, data dictionary, limitations, cross-node design |
| `notebooks/phase1_demo.ipynb` | Walk-through of the data and results |

## Assumptions and limits

Power in kW, battery state 100–500 kWh, 100 kW battery limit, 95 % efficiency, 400 V three-phase, power factors 0.99/0.98: all assumptions to confirm against the source model. Meter error is independent Gaussian noise; real meters also drift and have offsets. See [`docs/limitations.md`](docs/limitations.md) and [`docs/data_dictionary.md`](docs/data_dictionary.md).

## Licence and data

Code and documentation: MIT ([`LICENSE`](LICENSE)). The MIT licence does **not** cover the PV/wind values inherited from the supplied export; read [`data/README.md`](data/README.md) before redistributing the datasets.
