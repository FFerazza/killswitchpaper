"""D-012: direct fetch of RIS RIB dumps (bviews), bypassing the BGPStream broker.

The broker's RIS RIB metadata has gaps across the study period (see D-002),
but the dump files themselves are complete on data.ris.ripe.net and follow a
deterministic URL scheme:

    https://data.ris.ripe.net/{collector}/{YYYY.MM}/bview.{YYYYMMDD}.{HHMM}.gz

This module downloads a bview and replays it through pybgpstream's singlefile
interface, tagging elems with the originating collector so the D-002 guards
and audit columns work unchanged.
"""

from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.common.cache import download
from src.common.log import get_logger

log = get_logger("bgp.risfiles")

_BVIEW_INTERVAL_S = 8 * 3600  # RIS dumps bviews at 00:00, 08:00, 16:00 UTC


class CollectorElem:
    """Proxy overriding `.collector` on a pybgpstream elem.

    The singlefile interface doesn't know which collector a file came from,
    but D-002 accounting keys peers by collector.
    """

    __slots__ = ("_elem", "collector")

    def __init__(self, elem: Any, collector: str):
        self._elem = elem
        self.collector = collector

    def __getattr__(self, name: str) -> Any:
        return getattr(self._elem, name)


def bview_url(base: str, collector: str, ts: int) -> str:
    """URL of the RIS bview for snapshot `ts` (must lie on the 8h bview grid)."""
    if ts % _BVIEW_INTERVAL_S:
        raise ValueError(f"ts {ts} is not on the RIS bview grid (00/08/16 UTC)")
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return f"{base}/{collector}/{dt:%Y.%m}/bview.{dt:%Y%m%d}.{dt:%H%M}.gz"


def fetch_bview(base: str, collector: str, ts: int, cache_dir: Path) -> Path:
    """Download (or reuse cached) bview file; returns the local path."""
    url = bview_url(base, collector, ts)
    dest = cache_dir / collector / url.rsplit("/", 1)[-1]
    return download(url, dest)


def read_rib_file(path: Path, collector: str) -> Iterator[Any]:
    """Yield elems from a local MRT RIB dump, with `.collector` set.

    Raises StreamTransportError on corrupted records (D-002 rule a), exactly
    like the broker-backed stream.
    """
    import pybgpstream  # lazy: needs the C library, only guaranteed in Docker

    from src.bgp.stream import _FATAL_STATUSES, StreamTransportError

    stream = pybgpstream.BGPStream(data_interface="singlefile")
    stream.set_data_interface_option("singlefile", "rib-file", str(path))
    for rec in stream.records():
        if rec.status in _FATAL_STATUSES:
            raise StreamTransportError(
                f"collector {collector} file {path.name}: record status {rec.status!r} "
                "- dump incomplete/unparseable; aborting per D-002"
            )
        for elem in rec:
            yield CollectorElem(elem, collector)
