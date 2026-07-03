"""Thin wrapper around pybgpstream with a lazy import.

pybgpstream needs the libbgpstream C library, which is only guaranteed inside
the Docker image; importing lazily lets every other stage (and the tests) run
without it.

D-002 validity rule (a): a partially transferred or unparseable dump file must
abort the run, never degrade it silently. libbgpstream reports such failures as
record status "corrupted-source" / "corrupted-record", which we escalate to an
exception instead of skipping.
"""

from collections.abc import Iterator
from typing import Any

_FATAL_STATUSES = ("corrupted-source", "corrupted-record")


class StreamTransportError(RuntimeError):
    """A dump file failed to transfer or parse completely (D-002 rule a)."""


def open_stream(
    from_time: int,
    until_time: int,
    collectors: list[str],
    record_type: str,
) -> Iterator[Any]:
    """Yield BGPStream elems for [from_time, until_time). record_type: 'ribs' | 'updates'.

    Raises StreamTransportError if any record arrives corrupted, so callers
    never build outputs from a truncated stream.
    """
    try:
        import pybgpstream
    except ImportError as e:
        raise RuntimeError(
            "pybgpstream is not installed (it needs the libbgpstream C library). "
            "Run this stage inside the Docker image; see RUNNING.md."
        ) from e

    stream = pybgpstream.BGPStream(
        from_time=from_time,
        until_time=until_time,
        collectors=collectors,
        record_type=record_type,
    )
    for rec in stream.records():
        if rec.status in _FATAL_STATUSES:
            raise StreamTransportError(
                f"collector {rec.collector}: record status {rec.status!r} at t={rec.time} "
                "- dump transfer/parse incomplete; aborting per D-002"
            )
        for elem in rec:
            yield elem
