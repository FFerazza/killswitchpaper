# Project brief: Iran 2025–26 shutdown reconstruction pipeline

## What this repo is

Data pipeline for a measurement study reconstructing Iran's 2025–26 nationwide internet shutdown from BGP routing data and outage signals. The research question: how was the shutdown implemented, phase by phase — by what technical mechanism (filtering vs. control-plane withdrawal), in what sequence across operators, and with what selectivity in restoration.

This brief defines the objectives and structure. Your job is to scaffold the repo and implement the pipeline stages below. Do not write any analysis or paper prose — this repo is acquisition, processing, and figure-ready datasets only.

## Periodization (drives all time windows)

| Phase | Window | Character |
|-------|--------|-----------|
| P0 | baseline → late Dec 2025 (incl. June 2025 war blackouts as short-shutdown reference) | normal + reference event |
| P1 | late Dec 2025 → 27 Feb 2026 | throttling / selective blocking |
| P2 | 28 Feb 2026 onset | hard blackout, connectivity ~1% |
| P3 | Mar–May 2026 | plateau |
| P4 | 25–26 May 2026 → present | partial, tiered restoration (whitelist regime) |

Phase boundary dates are **hypotheses to verify against the data**, not constants to hard-code. Store them in one config file (`config/phases.yaml`) so they can be revised.

## Hypotheses the data must support testing

- **H1 (mechanism):** P1 = filtering (routes announced, active probing collapses); P2 = control-plane withdrawal. Requires BGP visibility and IODA signals on a shared timeline per AS.
- **H2 (topology):** disconnection executed at international gateway ASes (e.g. TIC / AS49666, AS12880), not per access network. Requires AS-path data: which upstreams disappear, whether domestic paths persist.
- **H3 (selectivity):** in P4, government/banking/state-media prefixes regain international visibility earlier and more completely than consumer/mobile prefixes. Requires per-prefix restoration timestamps joined to an AS classification.
- **H4 (rehearsal):** P2 execution faster/cleaner than Nov 2019 and June 2025 events. Same pipeline, pointed at those windows.

## Data sources and stages

### Stage 1 — Population: IR ASNs and prefixes
- Download RIPE NCC extended delegation file: `https://ftp.ripe.net/pub/stats/ripencc/delegated-ripencc-extended-latest`
- Parse all `IR` rows → ASN list, IPv4/IPv6 blocks (convert start+count to CIDR prefixes).
- Download latest CAIDA as2org dataset from `https://publicdata.caida.org/datasets/as-organizations/`, join org names onto IR ASNs.
- Output: `data/population/ir_asns.csv`, `data/population/ir_prefixes.csv`.
- Create `data/population/ir_asn_classification.csv` with columns `asn,org_name,type,notes` where `type ∈ {state_telecom, mobile, isp, government, financial, hosting, education, other}`. **Pre-fill asn and org_name programmatically; leave `type` blank for manual classification.** This file is a hand-curated research artifact — the code must never overwrite manual entries (merge, don't regenerate).

### Stage 2 — BGP visibility: RIS + RouteViews via pybgpstream
- Dependency: `pybgpstream` (needs libbgpstream C library — document install in README; provide a Dockerfile so the environment is reproducible).
- Two resolutions:
  - **RIB snapshots every 8h** across the full study period → per-prefix visibility fraction (peers seeing the prefix / total full-feed peers). Output: one parquet per snapshot in `data/bgp/ribs/`, plus a consolidated `data/bgp/visibility_timeseries.parquet`.
  - **Full update streams only in boundary windows** (defined in `config/phases.yaml`, e.g. 2026-02-27→03-01 and 2026-05-24→05-27) → withdrawal/re-announcement timestamps at minute resolution. Output: `data/bgp/events/{window}.parquet` with columns `ts,prefix,asn,event(withdraw|announce),peer_asn,as_path`.
- Use a radix tree (`py-radix`) to match observed prefixes against the IR population, including more-specifics.
- Retain AS paths (for H2: upstream identification, domestic vs. international visibility).
- Collectors: start with `rrc00`, `rrc12`, `route-views2`, `route-views.linx`; make the list configurable.
- **Must support incremental/resumable runs** — full-period processing is hours-to-days and tens of GB; a crash must not restart from zero. Cache raw pulls, skip completed snapshots.

### Stage 3 — IODA signals
- REST API, no key: `https://api.ioda.inetintel.cc.gatech.edu/v2/signals/raw/{entityType}/{entityCode}` with unix `from`/`until` params. **Verify host/path against current IODA docs at implementation time** — the API has moved between institutions.
- Pull country-level (`country/IR`) for the full period and per-ASN for every ASN in the population, all three signals (BGP, active probing, darknet).
- Output: `data/ioda/country_IR.parquet`, `data/ioda/asn/{asn}.parquet`.
- Rate-limit politely; cache responses; resumable.

### Stage 4 — RIPEstat validation
- `https://stat.ripe.net/data/routing-history/data.json?resource=AS{n}` for a configurable sample of ASNs.
- Purpose: independent cross-check of Stage 2 output. Output: `data/ripestat/{asn}.json` plus a small comparison script that flags disagreements between RIPEstat history and the pipeline's visibility series.

### Stage 5 — Joined analysis tables (figure-ready, no figures yet)
- `outputs/visibility_by_type.parquet` — visibility fraction over time, aggregated by classification type (H3).
- `outputs/bgp_vs_ioda.parquet` — per-AS timeline aligning BGP visibility with IODA active-probing and darknet signals; derive per-AS state: `announced_and_reachable | announced_but_dark | withdrawn` (H1).
- `outputs/upstream_transitions.parquet` — per-AS upstream sets over time from AS paths (H2).
- `outputs/event_speed.parquet` — onset duration metrics (time from first to last withdrawal) per event window, comparable across 2019 / June 2025 / Feb 2026 (H4).

## Repo structure to create

```
config/
  phases.yaml          # phase boundaries, event windows, collector list, ASN samples
  sources.yaml         # URLs, API endpoints
src/
  population/          # stage 1
  bgp/                 # stage 2
  ioda/                # stage 3
  ripestat/            # stage 4
  analysis/            # stage 5 joins
  common/              # radix matching, time utils, caching, io
data/                  # gitignored except population classification csv
outputs/               # gitignored
tests/
Dockerfile
README.md
Makefile               # make population / bgp-ribs / bgp-events / ioda / ripestat / analysis
```

## Constraints and conventions

- Python 3.11+, `requests`, `pybgpstream`, `py-radix`, `pandas`/`pyarrow`. Keep dependencies minimal.
- Every stage: a CLI entrypoint, idempotent, resumable, logs to stderr, writes only under `data/` or `outputs/`.
- All timestamps UTC, unix seconds in storage, ISO 8601 in logs.
- No hard-coded dates or ASNs outside `config/`.
- `data/` is gitignored **except** `data/population/ir_asn_classification.csv` (hand-curated, versioned).
- Tests: unit-test the delegation-file parser, CIDR conversion, radix matching, and the state derivation (announced_and_reachable / announced_but_dark / withdrawn) with small fixtures. No network calls in tests.

## Build order and first milestone

1. Scaffold structure, config files, Dockerfile, Makefile.
2. Stage 1 end-to-end (fully runnable, produces the population files).
3. Stage 2 **limited to one test week** — the P2 boundary window (2026-02-25 → 2026-03-03) — before any full-period run. Validate against Stage 4 on ~5 ASNs.
4. Stages 3–5 after Stage 2 is trusted.

**Milestone 1 definition of done:** `make population && make test-week` produces the population files, one week of visibility data, and a `bgp_vs_ioda` join for that week, with the comparison script showing agreement with RIPEstat on the sample ASNs.
