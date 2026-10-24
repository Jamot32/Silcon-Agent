"""Bounded deterministic physical recovery. Plans are not measured metrics."""
from dataclasses import dataclass
from decimal import Decimal
from app.eda.physics import number


@dataclass(frozen=True)
class RecoveryPlan:
    action: str
    overrides: dict
    reason: str
    target_relaxed: bool = False
    retry: bool = False


def recover_flow(failure_class, *, attempts, remaining_flows, current,
                 fixed_footprint=False, occupancy_pct=None, min_clock_mhz=None,
                 max_die_um=500):
    """A bounded next action. Caller executes, validates, accounts and emits it.

    No tool/model call occurs here. A retry consumes the original flow budget.
    Lower utilization alone cannot enlarge an absolute DIE_AREA.
    """
    if type(attempts) is not int or attempts < 0 or type(remaining_flows) is not int:
        raise ValueError("Recovery counters must be integers")
    if not isinstance(current, dict):
        raise ValueError("Resolved current configuration is required")
    if remaining_flows <= 0:
        return RecoveryPlan('stop', {}, 'Flow-run budget exhausted; retain partial artifacts.')
    if failure_class in {'die_too_small', 'routing_congestion', 'placement_failed'}:
        density = number(current.get('PL_TARGET_DENSITY_PCT'))
        occupancy = number(occupancy_pct, positive=False) if occupancy_pct is not None else None
        lowered = max(Decimal(30), density - 5)
        # Avoid asking a placer to target below its already measured occupancy.
        if attempts == 0 and lowered < density and (occupancy is None or occupancy < lowered):
            return RecoveryPlan('lower_density', {'PL_TARGET_DENSITY_PCT': float(lowered)},
                                'Try a less dense placement; absolute die dimensions stay explicit.', retry=True)
        if fixed_footprint:
            return RecoveryPlan('scope_down', {},
                                'The fixed footprint cannot be enlarged; reduce logic or request a larger footprint.')
        if attempts >= 2:
            return RecoveryPlan('stop', {}, 'Placement retries exhausted; reduce design size or inspect the saved placement diagnostic.')
        die = current.get('DIE_AREA')
        if not isinstance(die, list) or len(die) != 4:
            raise ValueError('Explicit absolute die bounds are required before growth')
        x0, y0, x1, y1 = [number(x, positive=False) for x in die]
        width, height = x1-x0, y1-y0
        if width <= 0 or height <= 0:
            raise ValueError('Invalid absolute die rectangle')
        width, height = width * Decimal('1.15'), height * Decimal('1.15')
        maximum = number(max_die_um)
        if x0+width > maximum or y0+height > maximum:
            return RecoveryPlan('scope_down', {}, 'Die growth would exceed the authorized absolute dimension limit.')
        return RecoveryPlan('grow_die', {'DIE_AREA': [float(x0), float(y0), float(x0+width), float(y0+height)]},
                            'Grow the standalone die by 15% per dimension; re-run physical verification.', retry=True)
    if failure_class == 'timing_fail':
        if min_clock_mhz is None:
            return RecoveryPlan('rtl_repair', {}, 'No authorized clock floor is present; preserve the requested timing target.')
        period, floor = number(current.get('CLOCK_PERIOD')), number(min_clock_mhz)
        slowest = 1000 / floor
        proposed = min(period * Decimal('1.10'), slowest)
        if proposed <= period or attempts >= 3:
            return RecoveryPlan('rtl_repair', {}, 'Clock relaxation is exhausted; a tested RTL change is required.')
        return RecoveryPlan('relax_clock', {'CLOCK_PERIOD': float(proposed)},
                            'Relax the timing constraint within the explicit user floor; retain the original target for comparison.',
                            target_relaxed=True, retry=True)
    if failure_class == 'drc_fail' and attempts == 0:
        density = number(current.get('PL_TARGET_DENSITY_PCT'))
        conservative = max(Decimal(30), density - 5)
        if conservative < density:
            return RecoveryPlan('conservative_drc_retry', {'PL_TARGET_DENSITY_PCT': float(conservative)},
                                'One conservative-density retry; only a real clean report can establish signoff.', retry=True)
    if failure_class == 'flow_timeout':
        return RecoveryPlan('scope_down', {}, 'The physical flow timed out; reduce design size or omit optional optimization rounds.')
    return RecoveryPlan('stop', {}, 'No deterministic repair applies; report the original diagnostic and retain partial artifacts.')
