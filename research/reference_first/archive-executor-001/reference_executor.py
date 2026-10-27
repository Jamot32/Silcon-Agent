"""Research-only host boundary. Generated model code runs only in Docker."""
import json

MAX_OBSERVATION = 65536
FIELDS = {'version', 'status', 'checked_steps', 'case_index', 'step_index', 'reason'}
REASONS = {'setup_error': 'setup_exception', 'invalid_output': 'output_shape',
           'model_error': 'model_exception', 'model_disagreement': 'literal_mismatch'}


def interpret_observation(returncode, timed_out, raw, case_lengths):
    """Reconcile host process facts with a bounded runner observation.

    This interprets evidence; it does not authenticate arbitrary model code or
    establish semantic correctness. The output deliberately avoids error text.
    """
    if timed_out is True:
        return {'status': 'timeout'}
    if type(timed_out) is not bool or type(returncode) is not int or returncode != 0:
        return {'status': 'process_error'}
    def invalid(): return {'status': 'invalid_observation'}
    if (type(raw) is not bytes or len(raw) > MAX_OBSERVATION or
            type(case_lengths) is not list or not case_lengths or len(case_lengths) > 32 or
            any(type(length) is not int or not 1 <= length <= 256 for length in case_lengths) or
            sum(case_lengths) > 2048):
        return invalid()
    try:
        def no_constant(_): raise ValueError('non-finite')
        def unique_pairs(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError('duplicate key')
                value[key] = item
            return value
        data = json.loads(raw, parse_constant=no_constant, object_pairs_hook=unique_pairs)
    except (UnicodeDecodeError, ValueError, RecursionError):
        return invalid()
    if type(data) is not dict or set(data) != FIELDS or type(data['version']) is not int or data['version'] != 1:
        return invalid()
    status, count, case, step, reason = (data[k] for k in ('status', 'checked_steps', 'case_index', 'step_index', 'reason'))
    if type(status) is not str or type(count) is not int or count < 0:
        return invalid()
    if status == 'passed':
        if count != sum(case_lengths) or case is not None or step is not None or reason is not None:
            return invalid()
    elif status == 'setup_error':
        if count != 0 or case is not None or step is not None or reason != REASONS[status]:
            return invalid()
    elif status in {'invalid_output', 'model_error', 'model_disagreement'}:
        if (type(case) is not int or not 0 <= case < len(case_lengths) or type(step) is not int or
                not 0 <= step < case_lengths[case] or count != sum(case_lengths[:case]) + step or
                reason != REASONS[status]):
            return invalid()
    else:
        return invalid()
    return data
