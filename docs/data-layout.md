# `data/` layout

What every folder holds, which stage writes it, and the rules that protect it.
Timestamps everywhere: **unix seconds (UTC)** in files, 8-hour snapshot grid
(00:00 / 08:00 / 16:00). Regenerate anything below via the commands noted —
nothing in `data/` is hand-made **except `population/ir_asn_classification.csv`**.

> `data/bgp/` and its subdirs are created root-owned by Docker; to add a dir as
> your user, `mkdir`+`chown` through a container (see memory/RUNNING notes).

## `data/population/` — who we measure (Stage 1)
Fixed study populations, derived from RIR delegation files. Written by
`python -m src.population`.
- `ir_asns.csv` — the 848 Iranian ASNs (the IR population).
- `ir_prefixes.csv` — their 2,516 delegated address blocks.
- `ir_asn_classification.csv` — **HAND-CURATED, never regenerate/overwrite.**
  Per-ASN `type` coding (state_telecom, mobile, ISP, …) for H3. Code only ever
  merges new ASNs in with `type` left blank.
- `control_prefixes.csv` + `.meta.json` — D-016: 427 delegated blocks of the 30
  frozen control ASNs (TR 124 / AE 169 / PK 134); meta records the delegation
  snapshot. Control ASN list itself lives in `config/controls.yaml` (write-once,
  D-014).

## `data/bgp/` — routing layer (Stage 2)
- `ribs/` — **primary series** snapshots: `rib_<unixts>.parquet`, one per 8h
  tick, RouteViews-only (route-views2 + linx, constant 118-peer instrument).
  Row = one announced prefix: `ts, prefix, cc, family, origin_asn, peers_seen,
  peers_total, visibility, upstreams, collector_fullfeed` (JSON audit column,
  D-002). `cc` = population tag (IR/TR/AE/PK; missing = IR in pre-D-016 files).
  Local copy holds the validated test week (Feb 25–Mar 3); the full 14-month
  series is produced on EC2 and will land here. Produced by
  `python -m src.bgp ribs` (D-017: dumps fetched directly from the archives,
  broker only as fallback).
- `visibility_timeseries.parquet` — concatenation of `ribs/` (rebuild by
  rerunning `ribs`; the inventory flags it when stale).
- `ribs_ris/` — **secondary (RIS-widened) series**: same schema, 4 collectors
  (+ rrc00/rrc12, ~380 peers), IR-only, 285 snapshots over five windows only:
  Sept 2025 baseline, Feb 2026 onset week, three calendar-rule plateau weeks,
  May 24–Jul 1 restoration. COMPLETE. Produced by `python -m src.bgp ribs-ris`
  (D-012/D-015). **Never mix the two series in one comparison** — different
  peer denominators.
- `visibility_timeseries_ris.parquet` — consolidation of `ribs_ris/`.
- `ribs_ec2_testweek/` — frozen validation copy: the D-016-tagged test week
  from EC2 (mixed transport, 11 broker + 7 direct). Keep as evidence.
- `ribs_ec2_directweek/` — frozen validation copy: fully direct-fetched test
  week (D-017 gate). Both proved identical to `ribs/` on IR rows via
  `python -m src.analysis.compare_ribs_runs`. Keep as evidence.
- `events/` — update streams (the play-by-play): `<window>.parquet`, one per
  configured event window, message-level announce/withdraw rows. Currently
  `feb2026_onset.parquet` (8.5M rows); `nov2019`, `jun2025`,
  `may2026_restoration` still to pull. Produced by `python -m src.bgp events`
  (broker transport — reliable for updates).

## `data/ioda/` — traffic layer (Stage 3)
Pulled from the IODA API (`python -m src.ioda`); signals per config:
`ping-slash24` (active probing), `merit-nt` (network telescope), `bgp`
(IODA's own routing summary — consistency check only, never evidence).
- `asn/` — `<asn>.parquet` per network, test-week window, 878 files
  (848 IR + 30 controls).
- `baseline/asn/` — same shape for the D-013 baseline month (Sept 2025);
  878 required files **+ 56 extra ASNs = D-014 selection screening leftovers
  (rejected control candidates) — benign, keep** (reused by the next-10
  robustness check).
- `baseline/country_IR.parquet`, `country_IR.parquet` — country-level Iran
  signals (incl. telescope) for baseline / test week.
- Full-period per-ASN pulls: NOT yet collected (planned final collection).

## `data/ripestat/` — cross-check (Stage 4)
`<asn>.json` routing-history responses for the 5 sample ASNs; behind the
90/90 agreement test in `outputs/ripestat_comparison.csv`. Produced by
`python -m src.ripestat`.

## `data/raw/` — transient download cache
- `ris/rrc00|rrc12/` — RIS bview dumps (D-012 direct fetch).
- `routeviews/route-views2|route-views.linx/` — RouteViews RIB dumps
  (D-017 direct fetch).
Files are deleted after their snapshot succeeds (and on parse failure, so a
truncated download can't poison a rerun). Anything lingering here is
re-downloadable; safe to clean when no worker is running.

## Checking completeness
`python -m src.analysis.inventory` — expected-vs-disk per series, staleness of
consolidated files, `--require <series...>` for a hard gate.
`python -m src.analysis.ribs_health <dir> --collectors ...` — per-snapshot QC.
