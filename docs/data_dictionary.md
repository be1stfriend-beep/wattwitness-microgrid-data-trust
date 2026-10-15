# Data dictionary — one-year simulated microgrid dataset

All power units are treated as kW unless confirmed otherwise. Both datasets are hourly from 2023-06-01 through 2024-05-31 inclusive (8,784 rows):

- `data/simulated_microgrid_1y.csv` — the **ideal state**, with every field below including the residual fields.
- `data/measured_telemetry_1y.csv` — the same channels as **meters would report them**: each numeric channel carries modelled error (0.5 % for power and current, 0.2 % for voltage, 0.3 % for battery state, 1 % for the curtailment estimate, plus a small floor), is rounded to 0.1 of its unit, and is empty during the 18 modelled device outages. A device that is off still reports exactly 0. The residual fields are not included; the detector recomputes them.

| Field | Meaning / provenance |
|---|---|
| `Timestamp` | Hourly timestamp. |
| `PV Power` | PV power from the supplied base simulation series; interpreted as AC output in this study. Verify original meaning and units. |
| `Wind Power` | Wind power retained from the supplied base simulation series. Its origin and measurement-versus-simulation status are inherited, not independently verified. |
| `Building Load` | Synthetic variable building demand. Not measured; EV load is not used. |
| `Grid Power` | Recalculated non-negative grid import under the assumption that export is disabled. |
| `Battery Power` | Recalculated signed battery power: positive means charging consumes bus power; negative means discharge supplies bus power. |
| `Battery SOC` | Recalculated stored-energy state, assumed range 100–500 kWh; not confirmed against the originating model. |
| `Curtailed Power` | Renewable surplus not used by load or battery due to assumed battery limits. |
| `Source Template Load (reference only)` | Original exported load used only to shape the synthetic demand profile; it is not treated as measured building demand. |
| `Building Context (synthetic)` | Generated weekday/weekend, seasonal and occasional high-demand labels; not measured activities. |
| `PV Inverter AC Output` | PV output under the current interpretation of `PV Power`. |
| `PV Inverter DC Input` | Derived from AC output using an assumed 97% efficiency. |
| `PV DC Voltage`, `PV DC Current` | Synthetic, calculated from derived DC input and an assumed voltage curve. |
| `PV Inverter AC Voltage LL`, `PV Inverter AC Current` | Synthetic, derived with nominal voltage and an assumed power factor of 0.99. |
| `Grid Voltage LL`, `Grid Current` | Synthetic, using a simple voltage-drop relation and an assumed power factor of 0.98. |
| `Battery Voltage`, `Battery Current` | Synthetic, using an assumed voltage map and signed battery power/efficiency. |
| Residual fields (ideal file only) | Calculated power-balance and electrical-consistency differences. They are ~0 because related signals are generated from the same simplified equations, which is why detection runs on the measured file. |
