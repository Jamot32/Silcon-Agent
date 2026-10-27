"""Trusted research driver, executed only inside the isolated container.

The model is untrusted code. Python restrictions are not a security boundary;
Docker isolation, resource limits and host-side reconciliation remain required.
"""
import builtins
import json
from pathlib import Path

ALLOWED = ('abs', 'all', 'any', 'bool', 'dict', 'enumerate', 'int', 'len', 'list',
           'max', 'min', 'range', 'reversed', 'sorted', 'sum', 'tuple', 'zip', '__build_class__')


def observation(status, checked=0, case=None, step=None, reason=None):
    return {'version': 1, 'status': status, 'checked_steps': checked,
            'case_index': case, 'step_index': step, 'reason': reason}


def evaluate():
    try:
        contract = json.loads(Path('/input/contract.json').read_text())
        cases = json.loads(Path('/input/examples.json').read_text())
        source = Path('/input/model.py').read_text()
        namespace = {'__builtins__': {name: getattr(builtins, name) for name in ALLOWED},
                     '__name__': 'reference_model'}
        exec(compile(source, '/input/model.py', 'exec'), namespace)
        model_class = namespace['Model']
        output_widths = {p['name']: p['width'] for p in contract['ports'] if p['direction'] == 'output'}
        synchronous = contract['profile'] == 'sync_active_low_all_known_after_rising_edge'
    except BaseException:
        return observation('setup_error', reason='setup_exception')
    checked = 0
    for case_index, case in enumerate(cases):
        try:
            model = model_class()
            if synchronous:
                model.reset()
        except BaseException:
            return observation('model_error', checked, case_index, 0, 'model_exception')
        for step_index, step in enumerate(case['steps']):
            try:
                inputs = dict(step['inputs'])
                output = model.step(inputs) if synchronous else model.evaluate(inputs)
            except BaseException:
                return observation('model_error', checked, case_index, step_index, 'model_exception')
            if (type(output) is not dict or set(output) != set(output_widths) or
                    any(type(output[name]) is not int or not 0 <= output[name] < (1 << width)
                        for name, width in output_widths.items())):
                return observation('invalid_output', checked, case_index, step_index, 'output_shape')
            if output != step['expected']:
                return observation('model_disagreement', checked, case_index, step_index, 'literal_mismatch')
            checked += 1
    return observation('passed', checked)


def main():
    result = evaluate()
    with Path('/output/observation.json').open('x', encoding='utf-8') as handle:
        json.dump(result, handle, allow_nan=False, separators=(',', ':'))
        handle.write('\n')


if __name__ == '__main__':
    main()
