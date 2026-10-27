"""Synthetic lifecycle tests: only the per-invocation Docker identity may be removed."""
import subprocess
import unittest
from reference_executor import run_owned_process

NAME = 'sa-ref-exec-' + 'a' * 32
ARGV = ['docker', 'run', '--rm', '--name', NAME, 'pinned-image']


class FakeProcess:
    def __init__(self, first, second=0):
        self.events = [first, second]
        self.killed = False

    def wait(self, timeout):
        result = self.events.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def kill(self):
        self.killed = True


class Result:
    def __init__(self, returncode): self.returncode = returncode


class OwnedProcessTests(unittest.TestCase):
    def test_interrupt_cleans_exact_container_and_waits_owned_child(self):
        process = FakeProcess(KeyboardInterrupt(), 130)
        cleanup = []
        def remove(argv, **kwargs):
            cleanup.append((argv, kwargs)); return Result(0)
        result = run_owned_process(ARGV, timeout_seconds=5, stdout=None, stderr=None,
                                   launch=lambda *a, **k: process, remove=remove)
        self.assertEqual(result['interruption_type'], 'KeyboardInterrupt')
        self.assertEqual(result['returncode'], 130)
        self.assertFalse(result['timed_out'])
        self.assertEqual(cleanup[0][0], ['docker', 'rm', '-f', NAME])
        self.assertTrue(result['cleanup']['ok'])
        self.assertFalse(process.killed)

    def test_timeout_cleanup_failure_never_becomes_success_and_kills_only_owned_child(self):
        process = FakeProcess(subprocess.TimeoutExpired(ARGV, 1), subprocess.TimeoutExpired(ARGV, 1))
        process.events.append(-9)
        result = run_owned_process(ARGV, timeout_seconds=1, stdout=None, stderr=None,
                                   launch=lambda *a, **k: process,
                                   remove=lambda *a, **k: Result(1))
        self.assertTrue(result['timed_out'])
        self.assertFalse(result['cleanup']['ok'])
        self.assertEqual(result['cleanup']['exit_code'], 1)
        self.assertTrue(process.killed)
        self.assertEqual(result['returncode'], -9)

    def test_interrupted_cleanup_is_preserved_and_owned_child_is_reaped(self):
        process = FakeProcess(KeyboardInterrupt(), 130)
        def remove(*a, **k): raise KeyboardInterrupt()
        result = run_owned_process(ARGV, timeout_seconds=1, stdout=None, stderr=None,
                                   launch=lambda *a, **k: process, remove=remove)
        self.assertEqual(result['interruption_type'], 'KeyboardInterrupt')
        self.assertFalse(result['cleanup']['ok'])
        self.assertEqual(result['cleanup']['error_type'], 'KeyboardInterrupt')
        self.assertEqual(result['returncode'], 130)

    def test_rejects_non_owned_or_ambiguous_container_names_before_launch(self):
        for argv in (['docker', 'run', '--name', 'someone-else'],
                     ARGV + ['--name', NAME], ['docker', 'rm', '--name', NAME]):
            with self.subTest(argv=argv), self.assertRaises(ValueError):
                run_owned_process(argv, timeout_seconds=1, stdout=None, stderr=None,
                                  launch=lambda *a, **k: self.fail('must not launch'))


if __name__ == '__main__':
    unittest.main()
