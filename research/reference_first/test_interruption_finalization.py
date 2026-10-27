"""Finalization faults must not replace cancellation or claim a receipt."""
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import run_reference
from executor_controls import fixture, GOOD


def interrupted(error):
    return {'returncode': 130, 'timed_out': False,
            'cleanup': {'ok': True, 'exit_code': 0, 'error_type': None},
            'launch_error': None, 'process_error': None, 'reap_error': None,
            'interruption_type': type(error).__name__, 'interruption': error}


class FinalizationFaultTests(unittest.TestCase):
    def test_hash_failure_does_not_replace_interrupt(self):
        primary = KeyboardInterrupt(); actual_sha = run_reference.sha; model_reads = 0
        def fault(path):
            nonlocal model_reads
            if path.name == 'model.py':
                model_reads += 1
                if model_reads == 2:
                    raise OSError('sensitive path must not be echoed')
            return actual_sha(path)
        with TemporaryDirectory(dir=run_reference.ROOT) as temporary:
            evidence = Path(temporary)/'case'
            with patch('run_reference.run_owned_process', return_value=interrupted(primary)), patch('run_reference.sha', side_effect=fault):
                with self.assertRaises(KeyboardInterrupt) as raised:
                    run_reference.run_bundle(*fixture(GOOD), evidence)
            self.assertIs(raised.exception, primary)
            self.assertTrue(any('OSError' in note and 'receipt not confirmed' in note for note in primary.__notes__))
            self.assertNotIn('sensitive path', str(primary.__notes__))
            self.assertFalse((evidence/'receipt.json').exists())

    def test_receipt_write_failure_does_not_replace_cancellation(self):
        primary = asyncio.CancelledError(); original = Path.write_text
        def fault(path, *args, **kwargs):
            if path.name == 'receipt.json':
                raise OSError('sensitive path must not be echoed')
            return original(path, *args, **kwargs)
        with TemporaryDirectory(dir=run_reference.ROOT) as temporary:
            evidence = Path(temporary)/'case'
            with patch('run_reference.run_owned_process', return_value=interrupted(primary)), patch.object(Path, 'write_text', fault):
                with self.assertRaises(asyncio.CancelledError) as raised:
                    run_reference.run_bundle(*fixture(GOOD), evidence)
            self.assertIs(raised.exception, primary)
            self.assertTrue(any('OSError' in note and 'receipt not confirmed' in note for note in primary.__notes__))
            self.assertNotIn('sensitive path', str(primary.__notes__))
            self.assertFalse((evidence/'receipt.json').exists())


if __name__ == '__main__':
    unittest.main()
