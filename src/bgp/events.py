"""Stage 2b: full update streams in boundary windows -> withdrawal/announcement events.

Output per window: data/bgp/events/{window}.parquet with columns
    ts, prefix, cc, asn, event(withdraw|announce), peer_asn, as_path
`cc` is the D-016 population tag (IR or a control country).
Withdrawals carry no AS path, so `asn` for a withdraw is the last origin this
peer announced for the prefix within the window (-1 if never seen).
"""

from pathlib import Path

import pandas as pd

from src.common.config import Config, Window
from src.common.log import get_logger
from src.common.prefixmatch import PrefixMatcher
from src.common.timeutil import to_iso
from src.bgp.stream import open_stream

log = get_logger("bgp.events")


def window_path(events_dir: Path, window: Window) -> Path:
    return events_dir / f"{window.name}.parquet"


def process_window(
    window: Window,
    collectors: list[str],
    matcher: PrefixMatcher,
    out_path: Path,
) -> None:
    if out_path.exists():
        log.info("skip existing %s", out_path.name)
        return
    log.info("window %s: %s -> %s", window.name, to_iso(window.start), to_iso(window.end))

    last_origin: dict[tuple[str, int, str], int] = {}  # (peer_addr, peer_asn, prefix) -> origin
    rows = []
    for elem in open_stream(window.start, window.end, collectors, "updates"):
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

    df = pd.DataFrame(
        rows, columns=["ts", "prefix", "cc", "asn", "event", "peer_asn", "as_path"]
    ).sort_values("ts").reset_index(drop=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(out_path)
    log.info("window %s: %d events -> %s", window.name, len(df), out_path)


def run_events(
    cfg: Config, events_dir: Path, populations: dict[str, list[str]], windows: list[Window]
) -> None:
    matcher = PrefixMatcher(populations)
    for window in windows:
        process_window(window, cfg.collectors, matcher, window_path(events_dir, window))
