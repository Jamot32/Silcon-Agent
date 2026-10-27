"""Fixed, hand-worked neutral controls for the container-only executor."""
import json
import os
from pathlib import Path
from app.agent.reference_bundle import contract_digest
from run_reference import run_bundle, sha

ROOT = Path(__file__).resolve().parent


def fixture(source):
    contract = {'schema_version': 1, 'profile': 'sync_active_low_all_known_after_rising_edge',
                'clock_port': 'clk', 'reset_port': 'rst_n', 'ports': [
                    {'name': 'clk', 'direction': 'input', 'width': 1},
                    {'name': 'rst_n', 'direction': 'input', 'width': 1},
                    {'name': 'clear', 'direction': 'input', 'width': 1},
                    {'name': 'enable', 'direction': 'input', 'width': 1},
                    {'name': 'amount', 'direction': 'input', 'width': 3},
                    {'name': 'q', 'direction': 'output', 'width': 3}]}
    def step(rst_n, clear, enable, amount, expected):
        return {'inputs': {'rst_n': rst_n, 'clear': clear, 'enable': enable, 'amount': amount},
                'expected': {'q': expected}}
    cases = [{'name': 'add_saturate_hold_clear', 'steps': [
                  step(0, 0, 1, 7, 0), step(1, 0, 1, 5, 5), step(1, 0, 1, 4, 7),
                  step(1, 0, 0, 7, 7), step(1, 1, 1, 3, 0)]},
             {'name': 'fresh_instance', 'steps': [step(0, 0, 1, 7, 0), step(1, 0, 1, 1, 1)]}]
    digest = contract_digest(contract)
    model = {'schema_version': 1, 'contract_sha256': digest, 'author_call_id': 'a'*32, 'source': source}
    examples = {'schema_version': 1, 'contract_sha256': digest, 'author_call_id': 'b'*32, 'cases': cases}
    return contract, model, examples


GOOD = '''class Model:
    def reset(self):
        self.q = 0
    def step(self, inputs):
        if not inputs["rst_n"] or inputs["clear"]:
            self.reset()
        elif inputs["enable"]:
            self.q = min(7, self.q + inputs["amount"])
        return {"q": self.q}
'''
WRONG = GOOD.replace('min(7, self.q + inputs["amount"])', '(self.q + inputs["amount"]) & 7')
INVALID = GOOD.replace('return {"q": self.q}', 'return {"q": True}')
ERROR = GOOD.replace('return {"q": self.q}', 'return {"q": 1 // 0}')


def main():
    requested = os.environ.get('SA_REFERENCE_EXEC_EVIDENCE')
    if not requested:
        raise SystemExit('Set SA_REFERENCE_EXEC_EVIDENCE to a new research evidence directory')
    root = Path(requested)
    if not root.is_absolute() or not root.resolve().is_relative_to(ROOT):
        raise SystemExit('Evidence must be a new absolute path inside research/reference_first')
    root.mkdir(mode=0o700, parents=False, exist_ok=False)
    expected = [('wrong', WRONG, 'model_disagreement'), ('good', GOOD, 'passed'),
                ('invalid', INVALID, 'invalid_output'), ('exception', ERROR, 'model_error')]
    results = {}
    for name, source, target in expected:
        contract, model, examples = fixture(source)
        receipt = run_bundle(contract, model, examples, root/name)
        results[name] = {'receipt_sha256': sha(root/name/'receipt.json'), 'status': receipt['outcome']['status'],
                         'returncode': receipt['returncode'], 'timed_out': receipt['timed_out'],
                         'observation_sha256': receipt['observation_sha256']}
        if receipt['outcome']['status'] != target or receipt['returncode'] != 0 or receipt['timed_out']:
            raise SystemExit(f'{name}: unexpected qualification result; evidence preserved')
    report = {'scope': 'hand-worked neutral reference/examples only; no RTL executed', 'scenarios': results,
              'sources_sha256': {name: sha(ROOT/name) for name in ('reference_executor.py',
                  'reference_executor_container.py', 'run_reference.py', 'executor_controls.py', 'test_executor.py')}}
    (root/'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': True, 'report_sha256': sha(root/'report.json'), 'scenarios': results}, sort_keys=True))


if __name__ == '__main__':
    main()
