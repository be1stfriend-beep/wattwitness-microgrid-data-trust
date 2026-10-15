# WattWitness architecture — Phase 1

```text
Supplied base simulation series (PV + wind)
        |
        v
Ideal state  (data/simulated_microgrid_1y.csv)
  - variable synthetic building load + synthetic context
  - battery dispatch, grid import and curtailment recomputed under assumptions
  - simplified inverter / voltage / current channels
        |
        v
Meter model  (scripts/add_measurement_noise.py, seed 7203)
  - 0.2-0.5 % measurement error, 0.1-unit resolution
  - device outages: 18 natural gaps, devices that report together drop together
        |
        v
Measured telemetry  (data/measured_telemetry_1y.csv)
        |
        +-------------------------------+
        |                               |
        v                               v
Training period (7,344 h)          Test window (1,440 h)
learn physics limits               clean copy + copy with 18 injected faults
fit Isolation Forest baseline                   |
        |                                       |
        +---------------+-----------------------+
                        v
   Data-quality rules              Physics cross-checks
   missing (17 channels)           6 residuals vs learned limits
   spike-and-return, frozen
                        |
                        v
   Explained alert: checks fired, mismatch vs limit, interpretation,
   evidence score (heuristic), suggested check, PENDING_REVIEW
                        |
                        v
   Human decision (confirm / likely genuine event / escalate / dismiss)
   appended to the review log; no automatic correction or control

Documented future design: privacy-preserving pattern summaries between nodes (cross_node_design.md).
```

## Core power-balance equation

With battery power positive while charging, grid power non-negative for imports and curtailment non-negative:

`PV inverter AC output + wind + grid import = building load + battery charging power + curtailed power`

Five further residuals compare PV DC power with DC voltage × current, PV AC and grid power with √3 · V_LL · I · PF, battery current with battery power, and the PV meter with the inverter output.

## Why a meter model

The voltage/current/inverter channels are derived from the same equations the detector checks, so in the ideal state every residual is ~0 by construction. Validating physics checks there would be circular. The meter model makes residuals realistic, and every physics limit is learned on the training period (99.9th percentile of |residual| + 20 %), never on the test window.

## Selected detector

An alert is raised if any data-quality rule fires or any physics residual exceeds its learned limit. Isolation Forest was evaluated as a baseline and in a "full hybrid"; it lowered precision and is not part of the selected detector. `app.py` only displays the outputs of `scripts/detect_evaluate.py`; it does not re-implement any rule or threshold.
