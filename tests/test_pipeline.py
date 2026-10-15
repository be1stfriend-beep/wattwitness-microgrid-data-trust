import sys, tempfile, unittest
from pathlib import Path
import pandas as pd
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from add_measurement_noise import add_measurement_effects, METERS
from inject_faults import inject
from detect_evaluate import FEATURES, calibrate_thresholds, detect, residuals, rule_checks
from review_log import REVIEW_COLUMNS, append_decision, latest_decisions, read_decisions


class DataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ideal = pd.read_csv(ROOT / 'data/simulated_microgrid_1y.csv', parse_dates=['Timestamp'])
        cls.measured = pd.read_csv(ROOT / 'data/measured_telemetry_1y.csv', parse_dates=['Timestamp'])

    def test_one_year_hourly_window(self):
        for df in (self.ideal, self.measured):
            self.assertEqual(len(df), 8784)
            self.assertEqual(str(df.Timestamp.iloc[0]), '2023-06-01 00:00:00')
            self.assertEqual(str(df.Timestamp.iloc[-1]), '2024-05-31 23:00:00')
            self.assertTrue(np.allclose(df.Timestamp.diff().dropna().dt.total_seconds() / 3600, 1.0))

    def test_load_is_variable_and_ev_is_absent(self):
        self.assertGreater(self.ideal['Building Load'].round(2).nunique(), 1000)
        self.assertNotIn('EV Load', self.ideal.columns)

    def test_ideal_state_is_exactly_consistent(self):
        r = residuals(self.ideal)
        self.assertLess(r['power_balance_kw'].abs().max(), 1e-4)
        self.assertLess(r['grid_kw'].abs().max(), 1e-4)

    def test_measured_telemetry_is_imperfect(self):
        r = residuals(self.measured)
        self.assertGreater(r['power_balance_kw'].abs().quantile(0.5), 0.1)  # meter error is visible
        self.assertLess(r['power_balance_kw'].abs().quantile(0.999), 10)   # but stays bounded
        gaps = self.measured[FEATURES].isna().any(axis=1)
        self.assertTrue(0 < gaps.mean() < 0.02)
        self.assertNotIn('Power Balance Residual', self.measured.columns)

    def test_measurement_is_reproducible_and_noise_free_at_scale_zero(self):
        a, gaps_a = add_measurement_effects(self.ideal.head(500))
        b, gaps_b = add_measurement_effects(self.ideal.head(500))
        pd.testing.assert_frame_equal(a, b)
        self.assertEqual(gaps_a, gaps_b)
        z, _ = add_measurement_effects(self.ideal.head(500), noise_scale=0, dropouts=False)
        self.assertLess((z[list(METERS)] - self.ideal.head(500)[list(METERS)]).abs().max().max(), 0.051)


class InjectionAndDetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.measured = pd.read_csv(ROOT / 'data/measured_telemetry_1y.csv', parse_dates=['Timestamp'])
        cls.clean, cls.faulted, cls.manifest = inject(cls.measured)
        cls.train = cls.measured.iloc[:-1440]
        cls.thr = calibrate_thresholds(cls.train)

    def test_fault_injection_has_traceable_labels(self):
        self.assertEqual(len(self.manifest), 18)
        self.assertEqual(set(self.manifest.fault_type), {'spike', 'frozen', 'gradual_drift', 'missing', 'delayed_signal', 'plausible_bias'})
        self.assertEqual(int(self.faulted.is_fault.sum()), int(self.manifest.altered_rows.sum()))

    def test_only_altered_rows_are_labelled(self):
        for ev in self.manifest.itertuples():
            labelled = self.faulted.index[self.faulted.fault_event_id.eq(ev.event_id)]
            sig = ev.affected_signal
            changed = [j for j in labelled if not self.faulted.at[j, sig] == self.clean.at[j, sig]]
            self.assertEqual(list(labelled), changed, ev.event_id)

    def test_injection_never_overlaps_natural_gaps(self):
        gap = self.clean[FEATURES].isna().any(axis=1)
        self.assertEqual(int((gap & self.faulted.is_fault.eq(1)).sum()), 0)

    def test_thresholds_come_from_training_period_only(self):
        poisoned = self.measured.copy()
        poisoned.loc[poisoned.index[-1440:], 'Grid Power'] += 500  # only the test window changes
        self.assertEqual(calibrate_thresholds(poisoned.iloc[:-1440]), self.thr)

    def test_spike_rule_ignores_steps_but_catches_spikes(self):
        df = pd.DataFrame({c: np.full(6, 50.0) for c in FEATURES})
        df.loc[3:, 'Grid Power'] = 250.0           # a step that stays: normal dispatch
        self.assertFalse(rule_checks(df)['spike']['Grid Power'].any())
        df.loc[3:, 'Grid Power'] = 50.0
        df.loc[3, 'Grid Power'] = 250.0            # a single-sample excursion
        self.assertEqual(list(np.flatnonzero(rule_checks(df)['spike']['Grid Power'])), [3])

    def test_detector_finds_most_faults_with_few_clean_alerts(self):
        scored = ~self.clean[FEATURES].isna().any(axis=1)
        pred = detect(self.faulted, self.thr)[0]['alert_rules_physics'][scored]
        y = self.faulted.is_fault[scored].astype(bool)
        self.assertGreater((pred & y).sum() / y.sum(), 0.8)
        clean_rate = detect(self.clean, self.thr)[0]['alert_rules_physics'][scored].mean()
        self.assertLess(clean_rate, 0.01)

    def test_operator_logs_do_not_leak_injection_labels(self):
        for name in ['alert_log.csv', 'baseline_alert_log.csv', 'review_queue.csv']:
            cols = pd.read_csv(ROOT / 'outputs' / name, nrows=2).columns
            for leak in ['is_fault', 'fault_type', 'fault_event_id']:
                self.assertNotIn(leak, cols, name)
        self.assertIn('fault_type', pd.read_csv(ROOT / 'outputs/evaluation_predictions.csv', nrows=2).columns)


class ReviewLogTests(unittest.TestCase):
    def test_damaged_log_is_backed_up_not_lost(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'log.csv'
            append_decision(path, {'scenario': 'Fault replay', 'event_timestamp': 't1', 'decision': 'Dismiss alert'})
            append_decision(path, {'scenario': 'Fault replay', 'event_timestamp': 't2', 'decision': 'Dismiss alert'})
            self.assertEqual(len(read_decisions(path)), 2)
            text = path.read_text(encoding='utf-8').splitlines()
            path.write_text('broken header\n' + '\n'.join(text[1:]) + '\n', encoding='utf-8')
            backup = append_decision(path, {'scenario': 'Fault replay', 'event_timestamp': 't3', 'decision': 'Dismiss alert'})
            self.assertIsNotNone(backup)
            self.assertEqual(len(backup.read_text(encoding='utf-8').splitlines()), 3)  # nothing lost
            self.assertEqual(list(read_decisions(path).columns), REVIEW_COLUMNS)

    def test_decisions_do_not_leak_across_views(self):
        log = pd.DataFrame([{'decision_timestamp': '1', 'scenario': 'Fault replay', 'event_timestamp': 't', 'decision': 'Confirm data issue'}])
        done = latest_decisions(log)
        self.assertIn(('Fault replay', 't'), done)
        self.assertNotIn(('Clean window', 't'), done)


class ReviewAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT))
        import app
        cls.app = app

    def test_every_alert_becomes_an_explained_case(self):
        log = pd.read_csv(ROOT / 'outputs/alert_log.csv')
        cases = self.app.view('fault')['alerts']
        self.assertEqual(len(cases), int(log.alert_rules_physics.sum()))
        for c in cases:
            self.assertTrue(c['headline'] and c['sentence'])
            self.assertEqual(len(c['checks']), 6)
            self.assertIn(c['chart']['kind'], ('pair', 'channels'))

    def test_decisions_are_validated_and_appended(self):
        with tempfile.TemporaryDirectory() as d:
            self.app.REVIEWS = Path(d) / 'log.csv'
            first = self.app.view('clean')['alerts'][0]['i']
            with self.assertRaises(ValueError):
                self.app.record_decision({'view': 'clean', 'i': first, 'decision': 'Delete everything'})
            with self.assertRaises(ValueError):
                self.app.record_decision({'view': 'clean', 'i': -5, 'decision': 'Dismiss alert'})
            rows = self.app.record_decision({'view': 'clean', 'i': first, 'decision': 'Dismiss alert', 'notes': 'ok'})
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['scenario'], 'Clean window')


class PackageTests(unittest.TestCase):
    def test_ui_and_readme_cover_the_four_official_goals(self):
        ui = (ROOT / 'ui/index.html').read_text(encoding='utf-8')
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        for phrase in ['Anomaly & Bias Detection', 'Confidence Scores & Explainability',
                       'Human-AI Escalation & Governance', 'Shared Learning Across the Noosphere']:
            self.assertIn(phrase, ui)
            self.assertIn(phrase, readme)

    def test_package_has_data_reports_and_no_raw_export(self):
        self.assertFalse((ROOT / 'data/base_simulation_export.csv').exists())
        for f in ['reports/phase1_report.pdf', 'reports/phase1_project_proposal.pdf', 'outputs/dataset_audit_summary.json']:
            self.assertTrue((ROOT / f).exists(), f)


if __name__ == '__main__':
    unittest.main(verbosity=2)
