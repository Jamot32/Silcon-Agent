"""Evaluator adapter around a human-authored exact rational reference.

The Fraction class is supplied by the pinned, unchanged CPython source in the
case. This file selects transactions and maps mathematical results to ports;
it is not represented as upstream human code or a candidate RTL solution.
"""
import random


def vectors(config, phase):
    width = config['reference_parameters']['WIDTH']
    scale = 1 << config['reference_parameters'].get('FBITS', 0)
    maximum = (1 << (width - 1)) - 1
    minimum = -(1 << (width - 1))
    if config['operation'] == 'unsigned_divide':
        limit = (1 << width) - 1
        result = [(0, 1), (1, 1), (7, 3), (limit, 1), (limit, limit), (1, limit), (10, 0)]
        rng = random.Random(config['seed'] + phase)
        return result + [(rng.randrange(limit + 1), rng.randrange(limit + 1)) for _ in range(24)]
    if config['operation'] == 'multiply':
        result = [(0, -1), (-1, 1), (scale, scale), (-scale, scale), (maximum, maximum), (minimum, 1), (minimum, -scale), (0, 0)]
        if width == 8 and scale == 16:
            result += [(120, 17), (-120, 17), (-121, 17)]
    else:
        result = [(scale, scale), (0, scale), (minimum, scale), (1, scale*2), (3, scale*2), (-3, scale*2), (maximum, 1), (minimum, -1), (10, 0), (0, 0), (scale, -scale)]
    rng = random.Random(config['seed'] + phase)
    return result + [(rng.randint(minimum, maximum), rng.randint(minimum, maximum)) for _ in range(24)]


def expected(config, a, b, Fraction):
    width = config['reference_parameters']['WIDTH']
    scale = 1 << config['reference_parameters'].get('FBITS', 0)
    mask = (1 << width) - 1
    if config['operation'] == 'unsigned_divide':
        if b == 0:
            return {'valid': 0, 'dbz': 1}
        quotient, remainder = divmod(a, b)
        return {'valid': 1, 'dbz': 0, 'val': quotient, 'rem': remainder}
    if config['operation'] == 'divide' and b == 0:
        return {'valid': 0, 'dbz': 1, 'ovf': 0}
    rational = Fraction(a * b, scale) if config['operation'] == 'multiply' else Fraction(a * scale, b)
    rounded = round(rational)
    overflow = not -(1 << (width-1)) <= rounded < (1 << (width-1))
    result = {'valid': int(not overflow), 'ovf': int(overflow)}
    if config['operation'] == 'divide':
        result['dbz'] = 0
    if not overflow:
        result['val'] = rounded & mask
    return result
