"""Host interruption produces a durable failure receipt before propagation."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from executor_controls import fixture, GOOD
from run_reference import ROOT, run_bundle


class InterruptReceiptTests(unittest.TestCase):
    def test_interrupt_writes_owned_cleanup_receipt_and_propagates(self):
        captured = KeyboardInterrupt()
        process = {'returncode': 130, 'timed_out': False,
                   'cleanup': {'ok': False, 'exit_code': 1, 'error_type': None},
                   'launch_error': None, 'process_error': None, 'reap_error': None,
                   'interruption_type': 'KeyboardInterrupt', 'interruption': captured}
        with TemporaryDirectory(dir=ROOT) as temporary:
            evidence = Path(temporary) / 'case'
            with patch('run_reference.run_owned_process', return_value=process):
                with self.assertRaises(KeyboardInterrupt):
                    run_bundle(*fixture(GOOD), evidence)
            receipt = json.loads((evidence/'receipt.json').read_bytes())
            self.assertEqual(receipt['outcome']['status'], 'interrupted')
            self.assertEqual(receipt['interruption_type'], 'KeyboardInterrupt')
            self.assertEqual(receipt['returncode'], 130)
            self.assertFalse(receipt['cleanup']['ok'])
            self.assertEqual(receipt['cleanup']['exit_code'], 1)


if __name__ == '__main__':
    unittest.main()
