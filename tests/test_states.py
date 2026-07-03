"""Unit tests for the H1 state derivation."""

import pytest

from src.analysis.states import (
    ANNOUNCED_AND_REACHABLE,
    ANNOUNCED_BUT_DARK,
    WITHDRAWN,
    derive_state,
)

VIS_MIN = 0.5
DARK_RATIO = 0.2


def _derive(visibility, probing, baseline):
    return derive_state(visibility, probing, baseline, VIS_MIN, DARK_RATIO)


def test_withdrawn_when_visibility_below_threshold():
    assert _derive(0.0, 100.0, 100.0) == WITHDRAWN
    assert _derive(0.49, 100.0, 100.0) == WITHDRAWN


def test_announced_and_reachable_when_probing_healthy():
    assert _derive(0.9, 95.0, 100.0) == ANNOUNCED_AND_REACHABLE


def test_announced_but_dark_when_probing_collapsed():
    # P1 signature: routes still announced, active probing collapsed
    assert _derive(0.9, 5.0, 100.0) == ANNOUNCED_BUT_DARK


def test_dark_threshold_boundary():
    # exactly at ratio*baseline is NOT dark (strictly below required)
    assert _derive(0.9, 20.0, 100.0) == ANNOUNCED_AND_REACHABLE
    assert _derive(0.9, 19.9, 100.0) == ANNOUNCED_BUT_DARK


def test_visibility_threshold_boundary():
    assert _derive(0.5, 100.0, 100.0) == ANNOUNCED_AND_REACHABLE


def test_missing_probing_defaults_to_reachable():
    # darkness requires positive evidence
    assert _derive(0.9, None, 100.0) == ANNOUNCED_AND_REACHABLE
    assert _derive(0.9, 5.0, None) == ANNOUNCED_AND_REACHABLE


def test_zero_baseline_defaults_to_reachable():
    assert _derive(0.9, 0.0, 0.0) == ANNOUNCED_AND_REACHABLE


@pytest.mark.parametrize("visibility", [0.0, 0.2, 0.49])
def test_withdrawn_wins_over_dark(visibility):
    # if routes are gone, probing state is irrelevant
    assert _derive(visibility, 0.0, 100.0) == WITHDRAWN
