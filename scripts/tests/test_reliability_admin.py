"""Sanitized aggregate fixture + explicitly synthetic reports/executor controls.

Never runs a sealer, evaluator, provider, model, subprocess or EDA tool.
"""
from copy import deepcopy
from dataclasses import replace
from collections import Counter
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import statistics
import tempfile
import unittest
from unittest.mock import patch

from app.reliability.public import (NotFound, PublicExportError, VerificationObservation, VerifierSpec,
                   export, load_admin, verify_summary)
from scripts.reliability_gate import CandidateRun, CommittedBaseline, MAKE, evaluate, main
from app.reliability.safeio import Files, LIMIT, canonical, decode, sha
from app.reliability.projection import CorpusSubsetIdentity, selection_sha256


REPO = Path(__file__).resolve().parents[2]
R1 = '20261024T030824Z_b4b21326'
SECRET = 'DO_NOT_EXPORT_PRIVATE_SPEC_ERROR_LOG_OR_PATH'


def stat(values):
    return dict(count=len(values), mean=statistics.mean(values) if values else None,
                median=statistics.median(values) if values else None,
                min=min(values) if values else None, max=max(values) if values else None)


def synthetic_candidate(baseline, *, medium_successes=None):
    """Unit-only derivative. Not claimed as a real new measurement or seal."""
    report = deepcopy(baseline)
    report['config']['repeats'] = 1
    report['config']['snapshot_id'] = 'e' * 64
    report['plan'] = [p for p in report['plan'] if p['tier'] in (1, 2)]
    rows = [r for r in report['trials'] if r['tier'] in (1, 2) and r['repeat_index'] == 0]
    for index, row in enumerate(r for r in rows if r['tier'] == 2):
        if medium_successes is not None:
            row['success'] = index < medium_successes
            row['failure_class'] = None if row['success'] else 'pipeline_failed'
    for row in rows:
        row['pipeline_sha'] = report['config']['snapshot_id']
    report['trials'] = rows
    def aggregate(old, group):
        out = deepcopy(old)
        n = len(group)
        success = sum(r['success'] for r in group)
        out.update(planned=n, recorded=n, attempted=n, blocked=0, missing=0,
                   successful=success, success_rate=success/n)
        out['stages'] = {name: {status: sum((r['hidden']['status'] if name == 'hidden' else r['stage_checks'][name]) == status for r in group)
            for status in old['stages'][name]} for name in old['stages']}
        out['measurements']['elapsed_seconds'] = stat([r['elapsed_seconds'] for r in group])
        out['cost']['unknown_attempted_trials'] = n
        out['failure_counts'] = dict(Counter(r['failure_class'] for r in group if not r['success']))
        return out
    report['totals'] = aggregate(report['totals'], rows)
    report['tiers'] = {str(tier): aggregate(report['tiers'][str(tier)], [r for r in rows if r['tier'] == tier])
                       for tier in (1, 2)}
    for group in report['tiers'].values():
        group['repeat_success_rates'] = stat([group['success_rate']])
    return report



def synthetic_reference():
    fixture = decode((REPO / 'backend/tests/fixtures/reliability/public-response.actual.json').read_bytes())
    public = next(c for c in fixture['cohorts'] if c['cohort_id'] == R1)['report']
    checks = ('rtl_generated','lint','self_tests','synthesis','flow','drc','lvs','package')
    statuses = ('pass','fail','not_run','unknown','error','not_applicable')
    rows, plan = [], []
    for tier, group in public['tiers'].items():
        for case in range(group['cases']):
            identity = format(int(tier)*100+case, '012x')
            plan.append(dict(case_id=identity,split='dev',tier=int(tier)))
            for repeat in range(3):
                success = case*3+repeat < group['successful']
                rows.append(dict(case_id=identity,split='dev',tier=int(tier),repeat_index=repeat,
                    success=success,attempted=True,provider='codex',pipeline_sha=public['pipeline_sha256'],
                    stage_checks={name: 'pass' if tier != '4' else 'not_run' for name in checks},
                    hidden=dict(status='pass' if tier != '4' else 'not_applicable',source_snapshot_sha256='a'*64),
                    source_kind='selected_flow' if tier != '4' else 'none',selected_source_sha256='a'*64 if tier != '4' else None,
                    elapsed_seconds=1.0,cost_usd=None,failure_class=None if success else 'budget_exceeded'))
    def aggregate(group, selected):
        value=deepcopy(group)
        value['measurements']={'elapsed_seconds':stat([r['elapsed_seconds'] for r in selected])}
        value['stages']={name:{status:sum((r['hidden']['status'] if name=='hidden' else r['stage_checks'][name])==status for r in selected) for status in statuses} for name in (*checks,'hidden')}
        value['reliability']={'harness_error_count':0}
        value['hidden_correctness_on_reported_success']={}
        return value
    total=dict(planned=90,recorded=90,attempted=90,blocked=0,missing=0,
        successful=public['successful'],success_rate=public['success_rate'],cost=deepcopy(public['cost']),failure_counts=deepcopy(public['failure_counts']))
    report=dict(schema_version=1,config={**public['comparison_conditions']['config'],'snapshot_id':public['pipeline_sha256']},
        plan=plan,trials=rows,corpus_sha256=public['comparison_conditions']['corpus_sha256'],
        provenance={key:deepcopy(public['comparison_conditions'][key]) for key in ('provider','model','cli_version','tool_versions')},
        totals=aggregate(total,rows),tiers={},target_assessment={})
    report['provenance']['harness_sha256']=public['comparison_conditions']['grader_sha256']
    for tier,group in public['tiers'].items():
        report['tiers'][tier]=aggregate(group,[r for r in rows if r['tier']==int(tier)])
    raw=canonical(report)
    seal=dict(schema_version=1,summary_sha256=sha(raw),terminal_records_sealed=90,
        corpus_sha256=report['corpus_sha256'],pipeline_sha256=public['pipeline_sha256'],
        measurement_harness_sha256=report['provenance']['harness_sha256'])
    return raw,canonical(seal)

class FakeExecutor:
    """Synthetic boundary receipt only. This class never executes its argv."""
    def __init__(self):
        self.calls = []
        self.change = None
        self.returncode = 0
        self.launched = True
        self.timeout = False

    def __call__(self, argv, cwd):
        self.calls.append((argv, cwd))
        report = decode((Path(cwd) / 'eval/results' / argv[2] / 'summary.json').read_bytes())
        raw = (Path(cwd) / 'eval/results' / argv[2] / 'summary.json').read_bytes()
        value = dict(verified=True, summary_sha256=sha(raw), terminal_records_sealed=report['totals']['planned'])
        if self.change:
            self.change(Path(cwd), argv[2], value)
        return VerificationObservation(argv, cwd, self.returncode, self.timeout, self.launched, canonical(value))


class AdminTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Synthetic unit report reconstructed from public aggregate statistics;
        # no raw measurements/private results are needed from a clean clone.
        cls.r1_raw, cls.r1_seal = synthetic_reference()
        cls.scripts = {name: (REPO / name).read_bytes() for name in
                       ('scripts/seal_eval.py', 'scripts/seal_harness_eval.py')}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo, self.public = self.root / 'private-host', self.root / 'public-exports'
        self.repo.mkdir(); self.public.mkdir()
        for name, raw in self.scripts.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        self.baseline = decode(self.r1_raw)
        self.put(R1, self.r1_raw, self.r1_seal)
        digest = sha(self.scripts['scripts/seal_eval.py'])
        self.spec = VerifierSpec('base', digest, digest)
        self.executor = FakeExecutor()

    def tearDown(self):
        self.temp.cleanup()

    def put(self, name, summary, sealed=None):
        raw = summary if type(summary) is bytes else canonical(summary)
        if sealed is None:
            seal = decode(self.r1_seal)
            report = decode(raw)
            seal.update(summary_sha256=sha(raw), terminal_records_sealed=report['totals']['planned'],
                        pipeline_sha256=report['config']['snapshot_id'], corpus_sha256=report['corpus_sha256'])
            sealed = canonical(seal)
        directory = self.repo / 'eval/results' / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'summary.json').write_bytes(raw)
        (directory / 'EVIDENCE.json').write_bytes(sealed)
        return raw, sealed

    def baseline_pointer(self):
        value = dict(schema_version=1, kind='kept_dev_baseline', kept=True, cohort_id=R1,
            summary_sha256=sha(self.r1_raw), seal_sha256=sha(self.r1_seal), repeats=3,
            sealer='base', sealer_sha256=self.spec.script_sha256, base_sealer_sha256=self.spec.base_sha256)
        raw = canonical(value)
        return CommittedBaseline('c' * 40, sha(raw), raw)

    def candidate(self, *, medium_successes=None):
        report = synthetic_candidate(self.baseline, medium_successes=medium_successes)
        raw, _ = self.put('UNIT_CANDIDATE', report)
        return CandidateRun(MAKE, True, 0, False, 'UNIT_CANDIDATE', report['config']['snapshot_id'], sha(raw))

    def test_sanitized_aggregates_bound_export_with_only_synthetic_verifier(self):
        row = export(self.repo, self.public, R1, self.spec, self.executor)
        result = load_admin(self.public, enabled=True)
        payload = result['cohorts'][0]
        report = payload['report']
        self.assertEqual((report['planned'], report['successful']), (90, 81))
        self.assertEqual((row['summary_sha256'], row['seal_sha256']), (sha(self.r1_raw), sha(self.r1_seal)))
        self.assertEqual(report['unknown_cost_trials'], 90)
        self.assertIsNone(report['cost']['median_usd'])
        self.assertEqual(result['top_original_failure_classes'][R1][0], {'class': 'budget_exceeded', 'count': 7})
        self.assertEqual(self.executor.calls[0][0], ('python3', 'scripts/seal_eval.py', R1, '--verify'))
        self.assertNotIn('trials', payload['report'])
        self.assertNotIn(self.baseline['plan'][0]['case_id'], json.dumps(result))
        self.assertEqual(len(list(self.public.iterdir())), 2)  # Export+index, no raw/seal copy.

    def test_private_text_dropped_and_unknown_nested_metrics_rejected(self):
        altered = deepcopy(self.baseline)
        altered['private_spec'] = SECRET
        for row in altered['trials']:
            row['error'] = SECRET
            row['private_file'] = '/private/hidden/source'
        self.put('UNIT_PRIVATE', altered)
        export(self.repo, self.public, 'UNIT_PRIVATE', self.spec, self.executor)
        self.assertNotIn(SECRET, json.dumps(load_admin(self.public, enabled=True)))
        altered['totals']['cost']['private_log'] = SECRET
        self.put('UNIT_NESTED', altered)
        with self.assertRaises(ValueError):
            export(self.repo, self.public, 'UNIT_NESTED', self.spec, self.executor)

    def test_disabled_is_404_without_open_and_missing_index_is_genuine_empty(self):
        with patch.object(Files, 'read', side_effect=AssertionError('must not read')):
            with self.assertRaises(NotFound):
                load_admin('/not/accessible', enabled=False)
        empty = load_admin(self.public, enabled=True)
        self.assertEqual((empty['state'], empty['cohorts'], empty['comparison_groups']), ('empty', [], []))

    def test_trends_join_only_identical_comparison_groups(self):
        export(self.repo, self.public, R1, self.spec, self.executor)
        second = deepcopy(self.baseline)
        second['config']['snapshot_id'] = 'a' * 64
        self.put('UNIT_SAME_GROUP', second)
        export(self.repo, self.public, 'UNIT_SAME_GROUP', self.spec, self.executor)
        third = deepcopy(self.baseline)
        third['config']['max_calls'] += 1
        self.put('UNIT_OTHER_GROUP', third)
        export(self.repo, self.public, 'UNIT_OTHER_GROUP', self.spec, self.executor)
        groups = load_admin(self.public, enabled=True)['comparison_groups']
        self.assertEqual(sorted(len(g['cohort_ids']) for g in groups), [1, 2])
        self.assertEqual(sorted(len(g['tier_trends']['1']) for g in groups), [1, 2])

    def test_no_verification_or_nonzero_timeout_launch_failure_cannot_publish(self):
        for field, value in [('returncode', 1), ('timeout', True), ('launched', False)]:
            executor = FakeExecutor(); setattr(executor, field, value)
            with self.subTest(field=field), self.assertRaises(ValueError):
                export(self.repo, self.public, R1, self.spec, executor)
        with self.assertRaises(ValueError):
            export(self.repo, self.public, R1, self.spec, None)
        self.assertEqual(list(self.public.iterdir()), [])

    def test_verifier_stdout_wrong_hash_and_changed_inputs_fail_closed(self):
        self.executor.change = lambda root, cohort, value: value.update(summary_sha256='0' * 64)
        with self.assertRaises(ValueError):
            verify_summary(self.repo, R1, self.spec, self.executor)
        def change(root, cohort, value):
            (root / 'eval/results' / cohort / 'EVIDENCE.json').write_text('{}')
        self.executor.change = change
        with self.assertRaisesRegex(ValueError, 'changed during'):
            verify_summary(self.repo, R1, self.spec, self.executor)

    def test_incomplete_heldout_regrade_and_fake_provider_refused(self):
        changes = [lambda r: r.update(aborted=True), lambda r: r['totals'].update(attempted=89),
                   lambda r: r['plan'][0].update(split='heldout'),
                   lambda r: r.update(artifact_kind='observation_regrade'),
                   lambda r: r['provenance'].update(provider='fake'), lambda r: r.update(is_replay=True)]
        for index, change in enumerate(changes):
            report = deepcopy(self.baseline); change(report)
            cohort = 'UNIT_BAD_' + str(index); self.put(cohort, report)
            with self.subTest(index=index), self.assertRaises(ValueError):
                export(self.repo, self.public, cohort, self.spec, self.executor)
        self.assertEqual(list(self.public.iterdir()), [])

    def test_source_seal_sha_sealer_and_path_attacks_rejected(self):
        for name in ('../outside', '/absolute', 'bad/name', 'bad\\name'):
            with self.assertRaises(ValueError):
                verify_summary(self.repo, name, self.spec, self.executor)
        with self.assertRaises(ValueError):
            verify_summary(self.repo, R1, replace(self.spec, script_sha256='0' * 64), self.executor)
        (self.repo / 'eval/results' / R1 / 'summary.json').write_text('{}')
        with self.assertRaises((ValueError, KeyError)):
            verify_summary(self.repo, R1, self.spec, self.executor)

    def test_duplicate_json_nonfinite_oversize_and_wrong_schema_refused(self):
        for raw in (b'{"schema_version":1,"schema_version":2}', b'{"n":NaN}', b'{"n":1e999}',
                    b' ' * (LIMIT + 1)):
            with self.assertRaises(ValueError):
                decode(raw)
        bad = deepcopy(self.baseline); bad['schema_version'] = True
        self.put('UNIT_BOOL_SCHEMA', bad)
        with self.assertRaises(ValueError):
            verify_summary(self.repo, 'UNIT_BOOL_SCHEMA', self.spec, self.executor)

    def test_duplicate_or_heldout_trial_rejected_before_any_verifier_call(self):
        for index, change in enumerate((lambda r: r['trials'][0].update(split='heldout'),
                                       lambda r: r['trials'].__setitem__(0, deepcopy(r['trials'][1])),
                                       lambda r: r['plan'].append(deepcopy(r['plan'][0])))):
            report = deepcopy(self.baseline); change(report)
            cohort = 'UNIT_FOREIGN_' + str(index); self.put(cohort, report)
            before = len(self.executor.calls)
            with self.assertRaises(ValueError):
                verify_summary(self.repo, cohort, self.spec, self.executor)
            self.assertEqual(len(self.executor.calls), before)

    def test_public_index_path_duplicate_hash_and_symlink_attacks_refused(self):
        row = export(self.repo, self.public, R1, self.spec, self.executor)
        original = (self.public / 'index.json').read_bytes()
        (self.public / 'index.json').chmod(0o600)  # Explicit hostile host mutation, not API capability.
        for change in [lambda i: i['exports'].append(i['exports'][0]),
                       lambda i: i['exports'][0].update(path='../summary.json'),
                       lambda i: i['exports'][0].update(sha256='0' * 64)]:
            index = decode(original); change(index)
            (self.public / 'index.json').write_bytes(canonical(index))
            with self.assertRaises(PublicExportError):
                load_admin(self.public, enabled=True)
        (self.public / 'index.json').write_bytes(original)
        path = self.public / row['path']; path.unlink()
        path.symlink_to(self.repo / 'eval/results' / R1 / 'summary.json')
        with self.assertRaises(PublicExportError):
            load_admin(self.public, enabled=True)

    def test_input_symlink_hardlink_and_public_eval_overlap_refused(self):
        source = self.repo / 'eval/results' / R1 / 'summary.json'
        original = source.read_bytes(); source.unlink()
        outside = self.root / 'outside'; outside.write_bytes(original)
        for mode in ('symlink', 'hardlink'):
            if mode == 'symlink': source.symlink_to(outside)
            else: os.link(outside, source)
            with self.assertRaises((ValueError, OSError)):
                verify_summary(self.repo, R1, self.spec, self.executor)
            source.unlink()
        source.write_bytes(original)
        with self.assertRaises(ValueError):
            export(self.repo, self.repo / 'eval/public', R1, self.spec, self.executor)
        ancestor = self.root / 'public-parent-alias'
        ancestor.symlink_to(self.repo / 'eval', target_is_directory=True)
        with self.assertRaises(ValueError):
            export(self.repo, ancestor / 'exports', R1, self.spec, self.executor)

    def test_existing_export_not_overwritten_and_failed_index_commit_not_faked(self):
        export(self.repo, self.public, R1, self.spec, self.executor)
        with self.assertRaises(ValueError):
            export(self.repo, self.public, R1, self.spec, self.executor)
        old = (self.public / 'index.json').read_bytes()
        report = deepcopy(self.baseline); self.put('UNIT_ATOMIC', report)
        with patch('app.reliability.safeio.os.replace', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):
                export(self.repo, self.public, 'UNIT_ATOMIC', self.spec, self.executor)
        self.assertEqual((self.public / 'index.json').read_bytes(), old)
        self.assertEqual(len(load_admin(self.public, enabled=True)['cohorts']), 1)

    def test_gate_binds_committed_n3_hash_and_current_real_command_receipt(self):
        candidate = self.candidate(medium_successes=8)
        result = evaluate(self.repo, self.baseline_pointer(), candidate, self.spec, self.executor)
        self.assertTrue(result['passed'])
        self.assertAlmostEqual(result['tiers']['2']['delta_points'], -10/3)
        self.assertEqual(result['baseline']['summary_sha256'], sha(self.r1_raw))
        self.assertEqual(len(self.executor.calls), 2)  # Both original seals verified.

    def test_gate_each_tier_independent_and_missing_receipt_not_substituted(self):
        candidate = self.candidate(medium_successes=7)
        result = evaluate(self.repo, self.baseline_pointer(), candidate, self.spec, self.executor)
        self.assertFalse(result['passed'])
        self.assertTrue(result['tiers']['1']['passed'])
        self.assertFalse(result['tiers']['2']['passed'])
        for changed in (replace(candidate, process_launched=False), replace(candidate, summary_sha256='0'*64),
                        replace(candidate, pipeline_sha256='0'*64), replace(candidate, cohort_id=R1),
                        replace(candidate, argv=('make', 'demo'))):
            with self.assertRaises(ValueError):
                evaluate(self.repo, self.baseline_pointer(), changed, self.spec, self.executor)
        with self.assertRaises(ValueError):
            evaluate(self.repo, self.baseline_pointer(), None, self.spec, self.executor)

    def test_uncommitted_pointer_or_changed_baseline_hash_cannot_pass(self):
        candidate = self.candidate(medium_successes=8)
        pointer = self.baseline_pointer()
        for changed in (replace(pointer, payload_sha256='0'*64), replace(pointer, commit_sha='worktree')):
            with self.assertRaises(ValueError):
                evaluate(self.repo, changed, candidate, self.spec, self.executor)
        body = decode(pointer.payload); body['summary_sha256'] = '0'*64
        raw = canonical(body)
        changed = CommittedBaseline(pointer.commit_sha, sha(raw), raw)
        with self.assertRaisesRegex(ValueError, 'last committed kept hash'):
            evaluate(self.repo, changed, candidate, self.spec, self.executor)

    def test_different_model_budget_or_infrastructure_not_regression_evidence(self):
        for field in ('model', 'budget', 'infrastructure'):
            report = synthetic_candidate(self.baseline, medium_successes=8)
            if field == 'model': report['provenance']['model'] = 'other-model'
            elif field == 'budget': report['config']['max_calls'] += 1
            else: report['totals']['reliability']['harness_error_count'] = 1
            raw, _ = self.put('UNIT_CANDIDATE', report)
            receipt = CandidateRun(MAKE, True, 0, False, 'UNIT_CANDIDATE', report['config']['snapshot_id'], sha(raw))
            with self.subTest(field=field), self.assertRaises(ValueError):
                evaluate(self.repo, self.baseline_pointer(), receipt, self.spec, self.executor)

    def test_cli_default_refuses_execution_and_returns_policy_exit_code(self):
        argv = ['--repo-root', str(self.repo), '--candidate-id', 'UNIT_CANDIDATE']
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(argv), 2)
        candidate = self.candidate(medium_successes=7)
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(argv, executor=self.executor, committed_reader=lambda path: self.baseline_pointer(),
                        candidate_receipt=candidate, candidate_spec=self.spec)
        self.assertEqual(code, 1)
        self.assertFalse(decode(output.getvalue().encode())['passed'])

    def test_subset_proof_binds_both_verified_reports_and_current_job(self):
        report = synthetic_candidate(self.baseline, medium_successes=8)
        report['corpus_sha256'] = 'd'*64
        raw, _ = self.put('UNIT_CANDIDATE', report)
        receipt = CandidateRun(MAKE, True, 0, False, 'UNIT_CANDIDATE', report['config']['snapshot_id'], sha(raw))
        proof = CorpusSubsetIdentity(self.baseline['corpus_sha256'], report['corpus_sha256'],
            selection_sha256(self.baseline['plan']), selection_sha256(report['plan']),
            sha(self.r1_raw), sha(raw), receipt.pipeline_sha256)
        with self.assertRaisesRegex(ValueError, 'Corpus fingerprint'):
            evaluate(self.repo, self.baseline_pointer(), receipt, self.spec, self.executor)
        self.assertTrue(evaluate(self.repo, self.baseline_pointer(), receipt, self.spec,
                                 self.executor, subset_identity=proof)['passed'])
        for field in ('baseline_summary_sha256', 'candidate_summary_sha256', 'candidate_pipeline_sha256'):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'sealed baseline/current-job'):
                evaluate(self.repo, self.baseline_pointer(), receipt, self.spec, self.executor,
                         subset_identity=replace(proof, **{field:'f'*64}))


if __name__ == '__main__':
    unittest.main()
