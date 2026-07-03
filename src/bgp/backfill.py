"""D-012: build the RIS-inclusive SECONDARY visibility series.

For each snapshot in the configured backfill ranges:
  - RouteViews elems come from the broker (as in the primary series),
  - RIS elems come from bview files fetched directly from data.ris.ripe.net,
  - both are chained into one snapshot with the full D-002 guard applied
    across all four collectors.

Outputs live in data/bgp/ribs_ris/ and consolidate into
data/bgp/visibility_timeseries_ris.parquet — a separate series that is never
mixed with the primary one inside a single comparison (D-012 rule 3).

Fetched bviews (~400 MB each) are deleted after their snapshot succeeds
unless keep_files=True; the download is re-done on retry, the parquet is not.
"""

from itertools import chain
from pathlib import Path

from src.common.config import Config
from src.common.log import get_logger
from src.common.prefixmatch import PrefixMatcher
from src.common.timeutil import snapshot_times, to_iso
from src.bgp.ribs import _RIB_MARGIN_S, process_snapshot, snapshot_path
from src.bgp.risfiles import fetch_bview, read_rib_file
from src.bgp.stream import open_stream

log = get_logger("bgp.backfill")


def run_ribs_ris(
    cfg: Config,
    ribs_dir: Path,
    cache_dir: Path,
    prefixes: list[str],
    keep_files: bool = False,
) -> None:
    """Process every backfill-range snapshot not yet on disk (resumable)."""
    matcher = PrefixMatcher(prefixes)
    base = cfg.source("ris_archive_base")
    ris_collectors = cfg.ris_backfill_collectors
    all_collectors = cfg.rib_collectors + ris_collectors

    for window in cfg.ris_backfill_ranges:
        times = list(snapshot_times(window.start, window.end, cfg.rib_interval_hours))
        log.info("range %s: %d snapshots (%s -> %s)",
                 window.name, len(times), to_iso(window.start), to_iso(window.end))
        for ts in times:
            out = snapshot_path(ribs_dir, ts)
            if out.exists():
                log.info("skip existing %s", out.name)
                continue
            # Fetch RIS files before opening the broker stream: fail early and
            # cheaply if the archive is missing a file.
            ris_files = [(fetch_bview(base, c, ts, cache_dir), c) for c in ris_collectors]
            elems = chain(
                open_stream(ts - _RIB_MARGIN_S, ts + _RIB_MARGIN_S, cfg.rib_collectors, "ribs"),
                *(read_rib_file(path, coll) for path, coll in ris_files),
            )
            process_snapshot(
                ts, all_collectors, matcher, cfg.full_feed_min_prefixes, out, elems=elems
            )
            if not keep_files:
                for path, _ in ris_files:
                    path.unlink(missing_ok=True)
