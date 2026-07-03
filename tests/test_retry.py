"""Snapshot-level retry on transient transport errors (D-002 abort semantics preserved)."""

import pytest

from src.bgp.ribs import retry_transport
from src.bgp.stream import StreamTransportError


def test_succeeds_after_transient_failures():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise StreamTransportError("partial file")

    retry_transport(flaky, attempts=3, delay_s=0)
    assert len(calls) == 3


def test_raises_after_exhausting_attempts():
    def always_broken():
        raise StreamTransportError("persistent corruption")

    with pytest.raises(StreamTransportError, match="persistent"):
        retry_transport(always_broken, attempts=2, delay_s=0)


def test_other_errors_are_not_retried():
    calls = []

    def wrong_error():
        calls.append(1)
        raise ValueError("bug, not transport")

    with pytest.raises(ValueError):
        retry_transport(wrong_error, attempts=3, delay_s=0)
    assert len(calls) == 1
