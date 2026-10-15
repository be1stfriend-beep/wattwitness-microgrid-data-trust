# Limitations and correct interpretation

1. **The building load is synthetic.** It varies by hour and day; it is not measured consumption. The repeated daily profile is only a shape template.
2. **Power units are assumed.** The original field definitions were not independently available; verify units before making physical claims.
3. **Battery state-of-charge meaning needs confirmation.** The source field ranges from 100 to 500. This prototype interprets it as 100–500 kWh of stored energy; it is an assumption.
4. **Voltage/current/inverter channels are derived.** They use simplified formulas, not a detailed device or circuit model, and are not sensor measurements.
5. **Meter error is modelled, not measured.** The measured telemetry adds independent Gaussian error (0.2–0.5 %), 0.1-unit resolution and random outages. Real meters also have offsets, temperature drift and correlated errors. Detection results depend on this model; see the sensitivity study in `outputs/noise_robustness.csv`.
6. **PV/wind provenance is inherited.** These series come from the supplied base simulation export; their origin and measurement-versus-simulation status are not independently verified.
7. **Faults are injected and single-channel.** The labelled events are controlled modifications of one signal at a time. They are not confirmed real attacks or equipment failures. A coordinated change of all related channels would pass the physics checks.
8. **Untouched data have no independent fault labels.** The alert rate on the clean window cannot be treated as a verified false-positive rate.
9. **Synthetic context is not measured.** Weekday/weekend, season and activity labels are assumptions and do not change the score.
10. **Genuine-event distinction is partial.** Physical inconsistency supports a data-quality hypothesis; a coherent multi-signal change is labelled as a potential operating event. Causality cannot be confirmed without trusted context and human review.
11. **The evidence score is not calibrated.** It expresses heuristic evidence strength, not the probability that a reading is faulty.
12. **Spikes are confirmed one hour late.** The spike-and-return rule needs the next sample.
13. **No cross-node validation.** The project has a single simulated node. Shared learning is documented design only.
14. **No real-world performance is established.** Results on controlled faults do not prove performance on equipment, other microgrids, factories or neighbourhoods.
15. **Human review is a prototype.** Decisions are appended to a local CSV; there is no authentication or secured audit storage. The prototype never repairs data or controls equipment.

## Before claiming physical validity

- Inspect the originating simulation model and verify units, battery energy/rate limits, efficiency and sign conventions.
- Replace assumed electrical properties and the meter model with equipment specifications or measured noise.
- Test with independently labelled cases, including coherent genuine operating events and data faults.
- Only perform laboratory validation after permission and an approved safe test plan.
