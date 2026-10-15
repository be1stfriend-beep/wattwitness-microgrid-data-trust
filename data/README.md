# Datasets

| File | What it is |
|---|---|
| `simulated_microgrid_1y.csv` | **Ideal state.** 8,784 hourly rows, 2023-06-01 to 2024-05-31. PV/wind from the supplied export, synthetic building load and context, recomputed dispatch, derived voltage/current/inverter channels. Every physical equation holds exactly; the residual columns document this. |
| `measured_telemetry_1y.csv` | **What meters would report.** The ideal state after the meter model in `scripts/add_measurement_noise.py` (seed 7203): 0.2–0.5 % measurement error, 0.1-unit resolution and 18 natural outages (39 rows with unknown values). The detector works on this file. |

Neither file is a field measurement. Regenerate the measured file with `python scripts/add_measurement_noise.py`; rebuild the ideal file from a permitted local export with `python scripts/build_simulated_microgrid_dataset.py --input PATH_TO_EXPORT`. The base export itself is not included.

## Data notice

The MIT licence in this repository covers code and documentation only. Both datasets keep PV and wind values derived from a supplied simulation export whose redistribution terms were not established by this project. Confirm you have the right to share them before publishing these files publicly.
