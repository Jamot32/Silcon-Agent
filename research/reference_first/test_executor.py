"""Research host receipt seam; no model is executed by these tests."""
import json
import unittest
from reference_executor import interpret_observation


def encoded(**changes):
    value = {'version': 1, 'status': 'passed', 'checked_steps': 3,
             'case_index': None, 'step_index': None, 'reason': None}
    value.update(changes)
    return json.dumps(value).encode()


class HostObservationTests(unittest.TestCase):
    def test_complete_success_and_functional_disagreement_are_distinct(self):
        self.assertEqual(interpret_observation(0, False, encoded(), [2, 1])['status'], 'passed')
        data = encoded(status='model_disagreement', checked_steps=1, case_index=0, step_index=1,
                       reason='literal_mismatch')
        self.assertEqual(interpret_observation(0, False, data, [2, 1])['status'], 'model_disagreement')

    def test_setup_invalid_output_and_model_error_are_distinct(self):
        for status, reason, case, step in [('setup_error', 'setup_exception', None, None),
                                           ('invalid_output', 'output_shape', 0, 0),
                                           ('model_error', 'model_exception', 0, 0)]:
            data = encoded(status=status, checked_steps=0, case_index=case, step_index=step, reason=reason)
            with self.subTest(status=status):
                self.assertEqual(interpret_observation(0, False, data, [2, 1])['status'], status)

    def test_host_failure_or_timeout_overrides_claimed_success(self):
        self.assertEqual(interpret_observation(1, False, encoded(), [2, 1])['status'], 'process_error')
        self.assertEqual(interpret_observation(0, True, encoded(), [2, 1])['status'], 'timeout')
        self.assertEqual(interpret_observation(None, False, encoded(), [2, 1])['status'], 'process_error')

    def test_bad_observation_is_not_a_pass(self):
        for raw in (None, b'{', b' ' * 65537, b'{"version":1,"status":"passed","status":"passed","checked_steps":3,"case_index":null,"step_index":null,"reason":null}', encoded(checked_steps=True), encoded(checked_steps=2),
                    encoded(status='model_disagreement', checked_steps=0, case_index=0, step_index=1,
                            reason='literal_mismatch'), encoded(extra='unexpected')):
            with self.subTest(raw=repr(raw)[:100]):
                self.assertEqual(interpret_observation(0, False, raw, [2, 1])['status'], 'invalid_observation')


if __name__ == '__main__':
    unittest.main()
