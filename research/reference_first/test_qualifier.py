"""Synthetic observations for the research qualifier's evidence boundary."""
import unittest
from qualify import validate_records


NAMES = ('test_reset_then_add', 'test_disabled_holds', 'test_saturates_instead_of_wrapping', 'test_clear_has_priority')
MUTANT = NAMES[2]
MESSAGE = 'DUT: expected 7, got 1'


def xml(names=NAMES, failed=None, message=MESSAGE, skipped=None):
    parts = []
    for name in names:
        child = (f'<failure error_type="AssertionError" error_msg="{message}" />' if name == failed else
                 '<skipped />' if name == skipped else '')
        parts.append(f'<testcase name="{name}" classname="test_reference">{child}</testcase>')
    return ('<testsuites><testsuite>' + ''.join(parts) + '</testsuite></testsuites>').encode()


def result(failed=False):
    return {'ok': not failed, 'passed': 3 if failed else 4, 'failed': int(failed), 'skipped': 0,
            'failures': [{'test': MUTANT, 'message': MESSAGE}] if failed else []}


class QualificationEvidence(unittest.TestCase):
    def test_good_and_expected_mutant_are_accepted(self):
        validate_records(xml(), result(), 'good')
        validate_records(xml(failed=MUTANT), result(True), 'wrap_mutant')

    def test_duplicate_or_wrong_test_names_are_rejected(self):
        for names in ((NAMES[0], NAMES[0], NAMES[2], NAMES[3]), (*NAMES[:3], 'unexpected')):
            with self.subTest(names=names), self.assertRaises(ValueError):
                validate_records(xml(names), result(), 'good')

    def test_non_integer_counts_are_rejected(self):
        for field, value in [('passed', True), ('failed', False), ('skipped', 0.0)]:
            data = result(); data[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_records(xml(), data, 'good')

    def test_runtime_and_xml_failure_must_agree_on_test_and_message(self):
        for mutate in ('test', 'message'):
            data = result(True); data['failures'][0][mutate] = 'wrong'
            with self.subTest(field=mutate), self.assertRaises(ValueError):
                validate_records(xml(failed=MUTANT), data, 'wrap_mutant')
        with self.assertRaises(ValueError):
            validate_records(xml(failed=MUTANT, message='different assertion'), result(True), 'wrap_mutant')

    def test_skipped_or_malformed_xml_is_rejected(self):
        for data in (xml(skipped=NAMES[0]), b'<testsuites', b'<!DOCTYPE x><testsuites/>'):
            with self.subTest(xml=data), self.assertRaises(ValueError):
                validate_records(data, result(), 'good')


if __name__ == '__main__':
    unittest.main()
