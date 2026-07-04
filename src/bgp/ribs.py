"""Stage 2a: RIB snapshots -> per-prefix visibility fraction.

For each snapshot time (every `rib_interval_hours` across the study period):
  - stream RIB dumps from the configured collectors,
  - count, per IR prefix, how many full-feed peers carry it,
  - visibility = peers seeing the prefix / total full-feed peers.

A peer is "full feed" if its RIB carries at least full_feed_min_prefixes
routes for that address family — partial-feed peers would bias visibility
downward, so they are excluded from both numerator and denominator.

One parquet per snapshot in data/bgp/ribs/ (skipped if present -> resumable),
then a consolidation pass builds data/bgp/visibility_timeseries.parquet.

D-002 snapshot validity: a snapshot is written only if the stream terminated
without transport errors (see src/bgp/stream.py) and every configured collector
contributed at least one full-feed peer; each parquet carries a per-collector
full-feed audit column so composition changes are detectable across the series.
"""

import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

from src.common.config import Config
from src.common.log import get_logger
from src.common.prefixmatch import PrefixMatcher
from src.common.timeutil import snapshot_times, to_iso
from src.bgp.stream import open_stream

log = get_logger("bgp.ribs")

# A RIB dump is not instantaneous; accept records within +/- this margin.
_RIB_MARGIN_S = 3600


class CollectorIntegrityError(RuntimeError):
    """A configured collector is missing from the snapshot (D-002 rule b)."""


def retry_transport(fn, attempts: int = 5, delay_s: float = 60.0) -> None:
    """Run `fn` up to `attempts` times, retrying on StreamTransportError.

    Dump transfers fail transiently (partial http downloads); a failed attempt
    writes nothing (D-002 abort semantics), so a clean retry is safe. Delay
    doubles each attempt (archive hiccups have outlasted a flat 3x60s window).
    Persistent corruption still raises after the last attempt.
    """
    import time

    from src.bgp.stream import StreamTransportError

    for attempt in range(1, attempts + 1):
        try:
            fn()
            return
        except StreamTransportError as e:
            if attempt == attempts:
                raise
            wait = delay_s * 2 ** (attempt - 1)
            log.warning("attempt %d/%d hit transport error (%s); retrying in %.0fs",
                        attempt, attempts, e, wait)
            time.sleep(wait)


def snapshot_path(ribs_dir: Path, ts: int) -> Path:
    return ribs_dir / f"rib_{ts}.parquet"


def per_collector_fullfeed(full_feed: dict[str, set[tuple]]) -> dict[str, dict[str, int]]:
    """Count full-feed peers per collector and family. Peer tuples start with the collector."""
    counts: dict[str, dict[str, int]] = {}
    for family, peers in full_feed.items():
        for peer in peers:
            collector = peer[0]
            counts.setdefault(collector, {"ipv4": 0, "ipv6": 0})[family] += 1
    return counts


def check_collector_integrity(
    counts: dict[str, dict[str, int]], collectors: list[str]
) -> None:
    """D-002 rule b: every configured collector must contribute >= 1 full-feed peer.

    Raises CollectorIntegrityError naming the missing collectors; the caller
    must abort the snapshot rather than write a file with a shifted denominator.
    """
    missing = [
        c for c in collectors
        if sum(counts.get(c, {}).values()) < 1
    ]
    if missing:
        raise CollectorIntegrityError(
            f"collectors with no full-feed peers: {missing} "
            f"(present: {sorted(counts)}) - snapshot aborted per D-002"
        )


def process_snapshot(
    ts: int,
    collectors: list[str],
    matcher: PrefixMatcher,
    full_feed_min: dict[str, int],
    out_path: Path,
    elems: "object | None" = None,
) -> None:
    """Build one snapshot parquet: prefix, origin_asn, peers_seen, peers_total, visibility, upstreams.

    `elems` overrides the default broker-backed stream — used by the D-012
    RIS backfill to chain broker and direct-file sources into one snapshot.
    The D-002 integrity guard runs against `collectors` either way.
    """
    # (collector, peer_asn, peer_addr) -> per-family route counts, for full-feed detection
    peer_route_counts: dict[tuple, dict[str, int]] = defaultdict(lambda: {"ipv4": 0, "ipv6": 0})
    # matched population prefix -> set of peers carrying it
    prefix_peers: dict[str, set[tuple]] = defaultdict(set)
    prefix_origins: dict[str, set[int]] = defaultdict(set)
    prefix_upstreams: dict[str, set[int]] = defaultdict(set)
    prefix_family: dict[str, str] = {}
    prefix_cc: dict[str, str] = {}  # D-016 population tag (IR or control country)

    if elems is None:
        elems = open_stream(ts - _RIB_MARGIN_S, ts + _RIB_MARGIN_S, collectors, "ribs")
    n_elems = 0
    for elem in elems:
        n_elems += 1
        prefix = elem.fields.get("prefix")
        if not prefix:
            continue
        family = "ipv6" if ":" in prefix else "ipv4"
        peer = (elem.collector, elem.peer_asn, elem.peer_address)
        peer_route_counts[peer][family] += 1

        matched = matcher.match_cc(prefix)
        if matched is None:
            continue
        prefix_peers[prefix].add(peer)
        prefix_family[prefix] = family
        prefix_cc[prefix] = matched[1]
        path = (elem.fields.get("as-path") or "").split()
        if path:
            try:
                origin = int(path[-1])
            except ValueError:  # AS sets like {64512,64513}
                continue
            prefix_origins[prefix].add(origin)
            if len(path) >= 2:
                try:
                    prefix_upstreams[prefix].add(int(path[-2]))
                except ValueError:
                    pass

    full_feed = {
        "ipv4": {p for p, c in peer_route_counts.items() if c["ipv4"] >= full_feed_min["ipv4"]},
        "ipv6": {p for p, c in peer_route_counts.items() if c["ipv6"] >= full_feed_min["ipv6"]},
    }
    collector_counts = per_collector_fullfeed(full_feed)
    cc_counts: dict[str, int] = defaultdict(int)
    for cc in prefix_cc.values():
        cc_counts[cc] += 1
    log.info(
        "%s: %d elems, %d peers (%d/%d full-feed v4/v6), %d prefixes seen %s, by collector %s",
        to_iso(ts), n_elems, len(peer_route_counts),
        len(full_feed["ipv4"]), len(full_feed["ipv6"]), len(prefix_peers),
        json.dumps(cc_counts, sort_keys=True),
        json.dumps(collector_counts, sort_keys=True),
    )
    check_collector_integrity(collector_counts, collectors)
    collector_audit = json.dumps(collector_counts, sort_keys=True)

    rows = []
    for prefix, peers in prefix_peers.items():
        family = prefix_family[prefix]
        total = len(full_feed[family])
        seen = len(peers & full_feed[family])
        origins = sorted(prefix_origins[prefix])
        rows.append({
            "ts": ts,
            "prefix": prefix,
            "cc": prefix_cc[prefix],
            "family": 4 if family == "ipv4" else 6,
            "origin_asn": origins[0] if origins else -1,
            "peers_seen": seen,
            "peers_total": total,
            "visibility": (seen / total) if total else 0.0,
            "upstreams": ",".join(str(a) for a in sorted(prefix_upstreams[prefix])),
            "collector_fullfeed": collector_audit,
        })
    df = pd.DataFrame(rows)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(out_path)


def run_ribs(
    cfg: Config, ribs_dir: Path, populations: dict[str, list[str]], start: int, end: int
) -> None:
    """Process every snapshot in [start, end), skipping ones already on disk."""
    from src.bgp.stream import StreamTransportError

    matcher = PrefixMatcher(populations)
    times = list(snapshot_times(start, end, cfg.rib_interval_hours))
    log.info("%d snapshots between %s and %s", len(times), to_iso(start), to_iso(end))
    failed: list[int] = []
    for ts in times:
        out = snapshot_path(ribs_dir, ts)
        if out.exists():
            log.info("skip existing %s", out.name)
            continue
        try:
            retry_transport(lambda: process_snapshot(
                ts, cfg.rib_collectors, matcher, cfg.full_feed_min_prefixes, out
            ))
        except StreamTransportError as e:
            # Nothing was written (D-002 abort semantics); skip so one bad
            # snapshot cannot stall the rest of the range, and report at end.
            log.error("giving up on snapshot %s after retries (%s); continuing",
                      to_iso(ts), e)
            failed.append(ts)
    if failed:
        raise SystemExit(
            f"{len(failed)} snapshot(s) failed after retries and are missing: "
            + ", ".join(to_iso(ts) for ts in failed)
            + " -- rerun to fill them (resumable)."
        )


def consolidate(ribs_dir: Path, out_path: Path) -> None:
    """Concatenate all snapshot parquets into visibility_timeseries.parquet."""
    files = sorted(ribs_dir.glob("rib_*.parquet"))
    if not files:
        log.warning("no snapshot files in %s; nothing to consolidate", ribs_dir)
        return
    df = pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)
    # Snapshots written before D-016 matched only the IR population, so a
    # missing/NaN cc tag is IR by construction.
    if "cc" not in df.columns:
        df["cc"] = "IR"
    else:
        df["cc"] = df["cc"].fillna("IR")
    df = df.sort_values(["ts", "prefix"]).reset_index(drop=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(out_path)
    log.info("visibility timeseries: %d rows -> %s", len(df), out_path)
