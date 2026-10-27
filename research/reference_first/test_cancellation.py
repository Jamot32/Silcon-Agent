"""Cancellation is a BaseException and still preserves owned cleanup/receipt."""
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from executor_controls import fixture, GOOD
from reference_executor import run_owned_process
from run_reference import ROOT, run_bundle


class Process:
    def __init__(self): self.waits = 0
    def wait(self, timeout):
        self.waits += 1
        if self.waits == 1: raise asyncio.CancelledError()
        return 137
    def kill(self): raise AssertionError('already reaped')


class Result:
    returncode = 0


class CancellationTests(unittest.TestCase):
    def test_cancellation_cleans_only_owned_container_and_is_propagated_after_receipt(self):
        name = 'sa-ref-exec-' + 'b' * 32
        commands = []
        def remove(argv, **kwargs):
            commands.append(argv)
            return Result()
        result = run_owned_process(['docker', 'run', '--name', name], timeout_seconds=1,
                                   stdout=None, stderr=None, launch=lambda *a, **k: Process(), remove=remove)
        self.assertEqual(commands, [['docker', 'rm', '-f', name]])
        self.assertEqual(result['interruption_type'], 'CancelledError')
        self.assertTrue(result['cleanup']['ok'])
        self.assertEqual(result['returncode'], 137)
        with TemporaryDirectory(dir=ROOT) as temporary:
            evidence = Path(temporary) / 'case'
            with patch('run_reference.run_owned_process', return_value=result):
                with self.assertRaises(asyncio.CancelledError):
                    run_bundle(*fixture(GOOD), evidence)
            receipt = json.loads((evidence/'receipt.json').read_bytes())
            self.assertEqual(receipt['outcome']['status'], 'interrupted')
            self.assertEqual(receipt['interruption_type'], 'CancelledError')
            self.assertTrue(receipt['cleanup']['ok'])


if __name__ == '__main__':
    unittest.main()
