"""Stage 2b: full update streams in boundary windows -> withdrawal/announcement events.

Output per window: data/bgp/events/{window}.parquet with columns
    ts, prefix, cc, asn, event(withdraw|announce), peer_asn, as_path
`cc` is the D-016 population tag (IR or a control country).
Withdrawals carry no AS path, so `asn` for a withdraw is the last origin this
peer announced for the prefix within the window (-1 if never seen).
"""

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from src.common.config import Config, Window
from src.common.log import get_logger
from src.common.prefixmatch import PrefixMatcher
from src.common.timeutil import to_iso, update_times
from src.bgp.stream import open_stream

log = get_logger("bgp.events")

_SCHEMA = pa.schema([
    ("ts", pa.int64()),
    ("prefix", pa.string()),
    ("cc", pa.string()),
    ("asn", pa.int64()),
    ("event", pa.string()),
    ("peer_asn", pa.int64()),
    ("as_path", pa.string()),
])
# Rows are flushed to disk in batches: a whole high-churn window held as
# Python dicts OOMs the host (nov2019 hit 25GB RSS). Output row order is
# stream arrival order, which BGPStream guarantees is time-sorted.
_FLUSH_ROWS = 2_000_000


def window_path(events_dir: Path, window: Window) -> Path:
    return events_dir / f"{window.name}.parquet"


def process_window(
    window: Window,
    collectors: list[str],
    matcher: PrefixMatcher,
    out_path: Path,
    elems=None,
    flush_rows: int = _FLUSH_ROWS,
) -> None:
    if out_path.exists():
        log.info("skip existing %s", out_path.name)
        return
    log.info("window %s: %s -> %s", window.name, to_iso(window.start), to_iso(window.end))
    if elems is None:
        elems = open_stream(window.start, window.end, collectors, "updates")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".parquet.tmp")
    writer = pq.ParquetWriter(tmp, _SCHEMA)
    last_origin: dict[tuple[str, int, str], int] = {}  # (peer_addr, peer_asn, prefix) -> origin
    rows: list[dict] = []
    n_written = 0

    def flush() -> None:
        nonlocal rows, n_written
        if rows:
            writer.write_table(pa.Table.from_pylist(rows, schema=_SCHEMA))
            n_written += len(rows)
            log.info("window %s: %d events written (stream at %s)",
                     window.name, n_written, to_iso(rows[-1]["ts"]))
            rows = []

    try:
        for elem in elems:
            if elem.type not in ("A", "W"):
                continue
            prefix = elem.fields.get("prefix")
            if not prefix:
                continue
            matched = matcher.match_cc(prefix)
            if matched is None:
                continue
            cc = matched[1]
            key = (elem.peer_address, elem.peer_asn, prefix)
            if elem.type == "A":
                path = (elem.fields.get("as-path") or "").split()
                try:
                    origin = int(path[-1]) if path else -1
                except ValueError:
                    origin = -1
                last_origin[key] = origin
                rows.append({
                    "ts": int(elem.time),
                    "prefix": prefix,
                    "cc": cc,
                    "asn": origin,
                    "event": "announce",
                    "peer_asn": int(elem.peer_asn),
                    "as_path": " ".join(path),
                })
            else:
                rows.append({
                    "ts": int(elem.time),
                    "prefix": prefix,
                    "cc": cc,
                    "asn": last_origin.get(key, -1),
                    "event": "withdraw",
                    "peer_asn": int(elem.peer_asn),
                    "as_path": "",
                })
            if len(rows) >= flush_rows:
                flush()
        flush()
        writer.close()
    except BaseException:
        # Leave nothing half-written: the retry ladder (and the skip check
        # above) must only ever see complete window files.
        writer.close()
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(out_path)
    log.info("window %s: %d events -> %s", window.name, n_written, out_path)


_PREFETCH_WORKERS = 8


def _iter_direct_ris(
    collectors: list[str], base: str, start: int, end: int, cache_dir: Path,
    keep_files: bool = False, max_workers: int = _PREFETCH_WORKERS,
):
    """D-021: yield elems from directly-fetched RIS update files, in order.

    A 15-day window is ~4,300 5-min files per collector; downloads are
    network-latency-bound (small files), so fetching serially measured
    ~5.5s/file (~13h combined for 2 collectors) against a broker that
    processes the same span in under an hour when it doesn't corrupt.

    Uses a sliding window of `max_workers` in-flight futures rather than
    submitting the whole collector's file list up front: `ThreadPoolExecutor`
    only bounds concurrently *executing* tasks, not completed-but-unconsumed
    ones, so eager submission lets fetching (I/O-bound, fast) race arbitrarily
    far ahead of replay (pybgpstream subprocess, slower) - a live run filled a
    32GB disk with ~2,400 undeleted files before the consumer caught up.
    Submitting the next file only as each one is consumed keeps at most
    `max_workers` files on disk at a time, replayed in chronological order per
    collector regardless of which download finishes first.
    """
    from collections import deque
    from concurrent.futures import ThreadPoolExecutor

    from src.bgp.risfiles import fetch_update, read_update_file

    for collector in collectors:
        times = iter(update_times(start, end))
        pool = ThreadPoolExecutor(max_workers=max_workers)
        pending: deque = deque()

        def submit_next() -> None:
            ts = next(times, None)
            if ts is not None:
                pending.append(pool.submit(fetch_update, base, collector, ts, cache_dir))

        try:
            for _ in range(max_workers):
                submit_next()
            while pending:
                fut = pending.popleft()
                submit_next()
                path = fut.result()
                try:
                    yield from read_update_file(path, collector)
                finally:
                    if not keep_files:
                        path.unlink(missing_ok=True)
        finally:
            # On error, don't block the D-021 broker fallback behind whatever
            # is still queued: drop unstarted work, let in-flight downloads
            # finish in the background.
            pool.shutdown(wait=False, cancel_futures=True)


def process_window_direct(
    window: Window,
    ris_collectors: list[str],
    rv_collectors: list[str],
    matcher: PrefixMatcher,
    out_path: Path,
    ris_base: str,
    cache_dir: Path,
    all_collectors: list[str],
    keep_files: bool = False,
) -> None:
    """D-021 primary transport for events: RIS collectors fetch update dumps
    directly; RouteViews collectors stay on the broker (D-017's original
    events scoping - unaffected by the D-021 incident, which was rrc00-only).

    Ordering across collectors doesn't need a global time-sorted merge:
    `process_window`'s per-key (peer_address, peer_asn, prefix) withdrawal
    attribution only requires each collector's own file sequence be
    chronological, which fetching one collector's files in ts order preserves;
    event_speed (H4) is verified order-independent regardless.
    """
    def elems():
        yield from _iter_direct_ris(
            ris_collectors, ris_base, window.start, window.end, cache_dir, keep_files
        )
        if rv_collectors:
            yield from open_stream(window.start, window.end, rv_collectors, "updates")

    process_window(window, all_collectors, matcher, out_path, elems=elems())


def run_events(
    cfg: Config,
    events_dir: Path,
    populations: dict[str, list[str]],
    windows: list[Window],
    ris_base: str | None = None,
    ris_cache_dir: Path | None = None,
) -> None:
    from src.bgp.ribs import retry_transport
    from src.bgp.stream import StreamTransportError

    matcher = PrefixMatcher(populations)
    ris_collectors = [c for c in cfg.collectors if c in cfg.ris_backfill_collectors]
    rv_collectors = [c for c in cfg.collectors if c not in ris_collectors]
    direct_ready = ris_base is not None and ris_cache_dir is not None and ris_collectors

    for window in windows:
        out = window_path(events_dir, window)
        if out.exists():
            log.info("skip existing %s", out.name)
            continue
        if direct_ready:
            try:
                process_window_direct(
                    window, ris_collectors, rv_collectors, matcher, out,
                    ris_base, ris_cache_dir, cfg.collectors,
                )
                continue
            except (StreamTransportError, RuntimeError) as e:
                log.warning(
                    "direct fetch failed for events window %s (%s); falling back to broker",
                    window.name, e,
                )
        # A failed attempt writes nothing (output lands atomically at window
        # end), so whole-window retries are safe; same transient broker
        # failures as ribs (see retry_transport).
        retry_transport(lambda: process_window(
            window, cfg.collectors, matcher, out
        ))
