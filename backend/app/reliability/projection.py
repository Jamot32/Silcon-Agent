"""Aggregate-only DEV report projection and separate CI gate policy."""
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
import math
import re


def require(condition, message):
    if not condition:
        raise ValueError(message)


def decode(raw):
    require(isinstance(raw, bytes) and 0 < len(raw) <= 2_000_000, 'Missing/oversized report')
    def reject(value):
        raise ValueError('Nonfinite JSON number: ' + value)
    def floating(value):
        result = float(value)
        require(math.isfinite(result), 'Nonfinite JSON number')
        return result
    value = json.loads(raw, parse_constant=reject, parse_float=floating)
    require(isinstance(value, dict) and value.get('schema_version') == 1, 'Unsupported report schema')
    return value


def fingerprint(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def project_dev_summary(raw, evidence):
    """Input must already have passed the historical sealer's verification.

    This cross-check is not a substitute for running that verifier. Only aggregate
    whitelist fields leave this function; no trial identity, text, file or path.
    """
    report = decode(raw)
    digest = sha256(raw).hexdigest()
    require(report.get('artifact_kind') != 'observation_regrade', 'A regrade is not a new measured cohort')
    require(evidence.get('summary_sha256') == digest, 'Summary differs from its sealed manifest')
    require(report.get('aborted') is not True, 'Aborted cohorts cannot be published as complete')
    plan = report['plan']
    require(plan and all(item['split'] == 'dev' for item in plan), 'This development projection accepts DEV only')
    total = report['totals']
    n = len(plan) * report['config']['repeats']
    require(n > 0 and total['planned'] == total['recorded'] == total['attempted'] == n
            and total['blocked'] == total['missing'] == 0, 'Incomplete report')
    for field, other in [('corpus_sha256', report['corpus_sha256']),
                         ('pipeline_sha256', report['config']['snapshot_id']),
                         ('measurement_harness_sha256', report['provenance']['harness_sha256'])]:
        require(fingerprint(other) and evidence.get(field) == other, 'Manifest provenance mismatch')
    rows = report['trials']
    require(len(rows) == n, 'Trial count mismatch')
    hardware = [r for r in rows if r['tier'] < 4]
    survivors = hardware[:]
    funnel = [{'check': 'planned_hardware', 'count': len(hardware)}]
    for check in ['rtl_generated', 'lint', 'self_tests', 'synthesis', 'flow', 'drc', 'lvs', 'package']:
        survivors = [r for r in survivors if r['stage_checks'].get(check) == 'pass']
        funnel.append({'check': check, 'count': len(survivors)})
    survivors = [r for r in survivors if r['hidden']['status'] == 'pass'
                 and r['source_kind'] == 'selected_flow' and r['selected_source_sha256']
                 and r['hidden']['source_snapshot_sha256'] == r['selected_source_sha256']]
    funnel.append({'check': 'bound_hidden_pass', 'count': len(survivors)})
    tiers = {}
    for tier, group in report['tiers'].items():
        tiers[tier] = {key: deepcopy(group[key]) for key in
                       ['cases', 'planned', 'recorded', 'attempted', 'successful', 'success_rate',
                        'repeat_success_rates', 'cost']}
        tiers[tier]['pipeline_time_seconds'] = deepcopy(group['measurements']['elapsed_seconds'])
    result = {
        'schema_version': 1, 'split': 'dev', 'complete': True,
        'source_summary_sha256': digest,
        'pipeline_sha256': report['config']['snapshot_id'],
        'grader_sha256': report['provenance']['harness_sha256'],
        'corpus_sha256': report['corpus_sha256'],
        'provider': report['provenance']['provider'], 'model': report['provenance']['model'],
        'repeats': report['config']['repeats'], 'planned': n,
        'successful': total['successful'], 'success_rate': total['success_rate'], 'tiers': tiers,
        'hardware_survival_funnel': funnel,
        'funnel_definition': 'Build tiers only; cumulative intersection of real passing checks, followed by source-bound hidden status. Scope outcomes excluded.',
        'independent_stage_checks': deepcopy(total['stages']),
        'failure_counts': deepcopy(total['failure_counts']),
        'failure_count_definition': 'Original automated grader classes; manual root-cause audits are separate evidence.',
        'cost': deepcopy(total['cost']),
        'pipeline_time_seconds': deepcopy(total['measurements']['elapsed_seconds']),
        'hidden_correctness_on_reported_success': deepcopy(total['hidden_correctness_on_reported_success']),
        'recorded_reliability': deepcopy(total['reliability']),
        'reliability_definition': 'Recorded proxy fields only. Unreviewed text is not proof of clear explanations.',
        'target_assessment': deepcopy(report['target_assessment']),
    }
    conditions = {
        'corpus_sha256':report['corpus_sha256'],
        'grader_sha256':report['provenance']['harness_sha256'],
        'provider':report['provenance']['provider'], 'model':report['provenance']['model'],
        'cli_version':report['provenance']['cli_version'],
        'tool_versions':deepcopy(report['provenance']['tool_versions']),
        'config':{key:value for key,value in report['config'].items() if key != 'snapshot_id'},
        'plan_sha256':sha256(json.dumps(plan,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
    }
    result['comparison_conditions'] = conditions
    result['comparison_group_sha256'] = sha256(json.dumps(conditions,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    # Data arrays have no case identity. Dollar values are not imputed for OAuth.
    result['time_distribution_seconds'] = [r['elapsed_seconds'] for r in rows]
    result['known_cost_distribution_usd'] = [r['cost_usd'] for r in rows if r['cost_usd'] is not None]
    result['unknown_cost_trials'] = sum(r['cost_usd'] is None for r in rows)
    return result


def selection_sha256(plan):
    return sha256(json.dumps(sorted((p['case_id'], p['tier']) for p in plan),
                             separators=(',', ':')).encode()).hexdigest()


@dataclass(frozen=True)
class CorpusSubsetIdentity:
    """Trusted host digest observation for this exact DEV T1/T2 CI subset only.

    Unlike eval-compare, this policy deliberately compares a subset with a full
    baseline. The unchanged evaluator hashes selected cases, so those two corpus
    digests differ. The host must rehash both selections; this is not a flag to
    waive corpus identity or a new grading rule.
    """
    full_corpus_sha256: str
    subset_corpus_sha256: str
    full_selection_sha256: str
    subset_selection_sha256: str
    baseline_summary_sha256: str
    candidate_summary_sha256: str
    candidate_pipeline_sha256: str

    def validate(self, baseline, candidate):
        require(all(fingerprint(value) for value in self.__dict__.values()), 'Invalid subset proof fingerprint')
        require(self.full_corpus_sha256 == baseline['corpus_sha256']
                and self.subset_corpus_sha256 == candidate['corpus_sha256']
                and self.full_selection_sha256 == selection_sha256(baseline['plan'])
                and self.subset_selection_sha256 == selection_sha256(candidate['plan'])
                and self.candidate_pipeline_sha256 == candidate['config']['snapshot_id'],
                'DEV corpus subset identity differs')


def regression_gate(baseline, candidate, *, max_drop_points=5, subset_identity=None):
    """Separate CI policy, not a paired before/after effect measurement.

    Baseline may have more repeats. Candidate must have all DEV T1/T2 cases N=1.
    Caller binds baseline to the last committed raw summary hash, verifies both
    manifests and retrieves these exact reports. No report/grader row is edited.
    """
    require(type(max_drop_points) in (int, float) and math.isfinite(max_drop_points)
            and 0 <= max_drop_points <= 100, 'Invalid regression threshold')
    require(baseline['schema_version'] == candidate['schema_version'] == 1, 'Unsupported report schema')
    require(candidate['config']['repeats'] == 1, 'CI candidate must be N=1')
    require(all(p['split'] == 'dev' and p['tier'] in (1, 2) for p in candidate['plan'])
            and candidate['plan'], 'CI candidate must contain only DEV T1/T2')
    expected = [p for p in baseline['plan'] if p['tier'] in (1, 2)]
    require(sum(p['tier'] == 1 for p in expected) == 8
            and sum(p['tier'] == 2 for p in expected) == 10, 'Committed baseline lacks the full DEV T1/T2 plan')
    require(expected == candidate['plan'], 'CI case plan differs from committed baseline subset')
    if subset_identity is None:
        require(baseline.get('corpus_sha256') == candidate.get('corpus_sha256')
                and fingerprint(baseline.get('corpus_sha256')), 'Corpus fingerprint differs')
    else:
        require(type(subset_identity) is CorpusSubsetIdentity, 'Trusted subset identity required')
        subset_identity.validate(baseline, candidate)
    for key in ['max_calls', 'max_tokens', 'max_usd', 'time_limit_seconds', 'concurrency']:
        require(baseline['config'][key] == candidate['config'][key], 'Different resource/budget configuration')
    for key in ['harness_sha256', 'provider', 'model', 'cli_version', 'tool_versions']:
        require(baseline['provenance'][key] == candidate['provenance'][key], 'Different grader/provider/tool provenance')
    for report in [baseline, candidate]:
        total = report['totals']
        planned = len(report['plan']) * report['config']['repeats']
        require(not report.get('aborted') and total['planned'] == total['recorded'] == total['attempted'] == planned
                and total['missing'] == total['blocked'] == total['reliability']['harness_error_count'] == 0,
                'A missing/aborted/infrastructure-error cohort cannot pass regression policy')
    deltas = {}
    for tier in ['1', '2']:
        before = baseline['tiers'][tier]['success_rate']
        after = candidate['tiers'][tier]['success_rate']
        require(before is not None and after is not None, 'Missing tier measurement')
        delta = 100 * (after - before)
        deltas[tier] = {'before': before, 'after': after, 'delta_points': delta,
                        'passed': delta >= -max_drop_points - 1e-9}
    return {'passed': all(item['passed'] for item in deltas.values()),
            'max_drop_points_per_tier': max_drop_points, 'tiers': deltas,
            'interpretation': 'N=1 regression policy against committed repeated means; not paired causal evidence or a new success-target claim.'}
