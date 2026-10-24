"""Pure policy controls; synthetic inputs never count as EDA measurements."""
import unittest
from app.agent.recovery import recover_flow


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.current = {'PL_TARGET_DENSITY_PCT': 45, 'FP_CORE_UTIL': 40,
                        'DIE_AREA': [0, 0, 100, 100], 'CLOCK_PERIOD': 20}

    def plan(self, failure, **kwargs):
        return recover_flow(failure, attempts=kwargs.pop('attempts', 0),
                            remaining_flows=kwargs.pop('remaining_flows', 3),
                            current=self.current, **kwargs)

    def test_density_key_and_units_match_pinned_librelane(self):
        plan = self.plan('routing_congestion', occupancy_pct=30)
        self.assertTrue(plan.retry)
        self.assertEqual(plan.overrides, {'PL_TARGET_DENSITY_PCT': 40.0})
        self.assertNotIn('PL_TARGET_DENSITY', plan.overrides)
        self.assertEqual(self.current['DIE_AREA'], [0, 0, 100, 100])

    def test_high_measured_occupancy_requires_die_growth(self):
        plan = self.plan('die_too_small', occupancy_pct=109.521)
        self.assertEqual(plan.action, 'grow_die')
        self.assertEqual(plan.overrides['DIE_AREA'], [0.0, 0.0, 115.0, 115.0])
        self.assertNotIn('FP_CORE_UTIL', plan.overrides)

    def test_fixed_footprint_never_grows(self):
        plan = self.plan('die_too_small', occupancy_pct=109.521, fixed_footprint=True)
        self.assertEqual(plan.action, 'scope_down')
        self.assertFalse(plan.retry)
        self.assertEqual(plan.overrides, {})

    def test_density_then_die_then_stop(self):
        self.assertEqual(self.plan('routing_congestion').action, 'lower_density')
        self.assertEqual(self.plan('routing_congestion', attempts=1).action, 'grow_die')
        self.assertEqual(self.plan('routing_congestion', attempts=2).action, 'stop')

    def test_clock_needs_explicit_floor(self):
        self.assertEqual(self.plan('timing_fail').action, 'rtl_repair')
        plan = self.plan('timing_fail', min_clock_mhz=40)
        self.assertEqual(plan.overrides, {'CLOCK_PERIOD': 22.0})
        self.assertTrue(plan.target_relaxed)
        self.current['CLOCK_PERIOD'] = 24
        self.assertEqual(self.plan('timing_fail', min_clock_mhz=40).overrides,
                         {'CLOCK_PERIOD': 25.0})
        self.current['CLOCK_PERIOD'] = 25
        self.assertFalse(self.plan('timing_fail', min_clock_mhz=40).retry)

    def test_bounded_clock_attempts(self):
        self.assertFalse(self.plan('timing_fail', attempts=3, min_clock_mhz=1).retry)

    def test_no_budget_no_retry(self):
        for failure in ['die_too_small', 'routing_congestion', 'timing_fail', 'drc_fail']:
            with self.subTest(failure=failure):
                plan = self.plan(failure, remaining_flows=0, min_clock_mhz=40)
                self.assertFalse(plan.retry)
                self.assertEqual(plan.overrides, {})

    def test_drc_one_retry_and_lvs_requires_diagnosis(self):
        self.assertTrue(self.plan('drc_fail').retry)
        self.assertFalse(self.plan('drc_fail', attempts=1).retry)
        self.assertFalse(self.plan('lvs_fail').retry)

    def test_timeout_has_usable_scope_action(self):
        plan = self.plan('flow_timeout')
        self.assertEqual(plan.action, 'scope_down')
        self.assertIn('reduce design size', plan.reason)

    def test_unknown_is_honest_stop(self):
        self.assertEqual(self.plan('unrecognized').action, 'stop')

    def test_unbounded_or_bad_rectangle_rejected(self):
        self.current['DIE_AREA'] = [0, 0, 0, 100]
        with self.assertRaises(ValueError):
            self.plan('die_too_small', occupancy_pct=109)
        self.current['DIE_AREA'] = [0, 0, 490, 490]
        self.assertEqual(self.plan('die_too_small', occupancy_pct=109).action, 'scope_down')


if __name__ == '__main__':
    unittest.main()
