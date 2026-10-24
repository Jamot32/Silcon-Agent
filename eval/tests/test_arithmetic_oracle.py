"""Literal arithmetic qualifications; synthetic cases, no benchmark attempts."""

from fractions import Fraction

import pytest

from eval.oracles.arithmetic import expected, vectors


def config(operation):
    return {"operation": operation, "reference_parameters": {"WIDTH": 8, "FBITS": 4}, "seed": 42}


@pytest.mark.parametrize("a,b,result", [
    (0, -1, {"valid": 1, "ovf": 0, "val": 0}),
    (-1, 1, {"valid": 1, "ovf": 0, "val": 0}),
    (1, 8, {"valid": 1, "ovf": 0, "val": 0}),
    (3, 8, {"valid": 1, "ovf": 0, "val": 2}),
    (-3, 8, {"valid": 1, "ovf": 0, "val": 254}),
    (16, 16, {"valid": 1, "ovf": 0, "val": 16}),
    (120, 17, {"valid": 0, "ovf": 1}),
    (-120, 17, {"valid": 1, "ovf": 0, "val": 128}),
    (-121, 17, {"valid": 0, "ovf": 1}),
    (-128, 16, {"valid": 1, "ovf": 0, "val": 128}),
    (-128, -16, {"valid": 0, "ovf": 1}),
])
def test_multiply_uses_signed_value_zero_and_post_round_overflow(a, b, result):
    assert expected(config("multiply"), a, b, Fraction) == result


@pytest.mark.parametrize("a,b,result", [
    (16, 16, {"valid": 1, "ovf": 0, "dbz": 0, "val": 16}),
    (0, 16, {"valid": 1, "ovf": 0, "dbz": 0, "val": 0}),
    (-128, 16, {"valid": 1, "ovf": 0, "dbz": 0, "val": 128}),
    (-128, -16, {"valid": 0, "ovf": 1, "dbz": 0}),
    (1, 32, {"valid": 1, "ovf": 0, "dbz": 0, "val": 0}),
    (3, 32, {"valid": 1, "ovf": 0, "dbz": 0, "val": 2}),
    (-3, 32, {"valid": 1, "ovf": 0, "dbz": 0, "val": 254}),
    (0, 0, {"valid": 0, "dbz": 1, "ovf": 0}),
    (127, 0, {"valid": 0, "dbz": 1, "ovf": 0}),
])
def test_divide_is_ordinary_signed_math_including_zero_and_minimum(a, b, result):
    assert expected(config("divide"), a, b, Fraction) == result


@pytest.mark.parametrize("a,b,result", [
    (255, 1, {"valid": 1, "dbz": 0, "val": 255, "rem": 0}),
    (7, 3, {"valid": 1, "dbz": 0, "val": 2, "rem": 1}),
    (1, 255, {"valid": 1, "dbz": 0, "val": 0, "rem": 1}),
    (0, 0, {"valid": 0, "dbz": 1}),
])
def test_unsigned_division_qualifies_quotient_remainder_and_dbz(a, b, result):
    assert expected(config("unsigned_divide"), a, b, Fraction) == result


def test_directed_vectors_cover_upstream_bug_boundaries_before_random_stimuli():
    multiply = vectors(config("multiply"), 0)
    assert {(0, -1), (-1, 1), (120, 17), (-120, 17), (-121, 17)} <= set(multiply)
    divide = vectors(config("divide"), 0)
    assert divide[:2] == [(16, 16), (0, 16)]
    assert {(-128, 16), (1, 32), (3, 32), (-3, 32), (10, 0)} <= set(divide)
