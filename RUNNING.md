# Testing and running the pipeline

This guide covers, for each stage: **(1) how to test it** cheaply before
trusting it, and **(2) how to run it fully** once tested. Read the top-level
`README.md` first for what each stage produces and why.

## One-time setup

### Local (everything except Stage 2)

```bash
cd killswitchpaper
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Stages 1, 3, 4 and 5 run locally. Stage 2 (BGP) needs `pybgpstream`, which
needs the libbgpstream C library — use the Docker image for it.

### Docker (required for Stage 2, works for everything)

```bash
make docker-image     # builds libbgpstream from source; takes a few minutes
```

Run any stage in the container with `data/` and `outputs/` mounted so results
land in the repo:

```bash
docker run --rm -v "$PWD/data:/app/data" -v "$PWD/outputs:/app/outputs" \
    killswitch-pipeline -m src.bgp ribs --window test_week
```

## Unit tests (no network, run these first and after every change)

```bash
make test             # = .venv/bin/python -m pytest -q
```

Covers the delegation-file parser, IPv4 count→CIDR conversion, radix
prefix matching (incl. more-specifics), the H1 state derivation
(`announced_and_reachable` / `announced_but_dark` / `withdrawn`), the
classification merge (manual entries must survive), and the UTC time grid.
All fixtures are inline; no test touches the network.

---

## Stage 1 — Population (`src/population`)

**What it does:** downloads the RIPE delegation file + CAIDA as2org, writes
`data/population/ir_asns.csv`, `ir_prefixes.csv`, and merges
`ir_asn_classification.csv` (never overwriting your manual `type`/`notes`).

**Test it:**
```bash
.venv/bin/python -m pytest tests/test_delegation.py tests/test_classification.py -v
```
Then a real run is itself cheap (~30 MB of downloads, under a minute):
```bash
make population
head data/population/ir_asns.csv data/population/ir_prefixes.csv
```
Sanity checks: several hundred ASNs; a few thousand prefixes; AS12880 and
AS49666 present in `ir_asns.csv`; org names filled in the classification CSV.

**Run it fully:** same command — `make population`. Re-running is safe and
idempotent: downloads are cached (`--force` re-fetches), and the
classification file is merged, not regenerated. After the first run, open
`data/population/ir_asn_classification.csv` and fill the `type` column by
hand (`state_telecom, mobile, isp, government, financial, hosting,
education, other`). Your entries are preserved by all later runs and the
file is versioned in git — commit it.

## Stage 2 — BGP visibility (`src/bgp`) — Docker

**What it does:** `ribs` builds 8-hourly per-prefix visibility fractions
(`data/bgp/ribs/*.parquet` → `data/bgp/visibility_timeseries.parquet`);
`events` extracts withdraw/announce events at minute resolution in the
boundary windows (`data/bgp/events/{window}.parquet`).

**Test it (do NOT start with the full period):**
```bash
# 1. One single snapshot interval (~minutes, validates the plumbing):
docker run --rm -v "$PWD/data:/app/data" killswitch-pipeline \
    -m src.bgp ribs --start 2026-02-25T00:00:00Z --end 2026-02-25T08:00:01Z

# 2. The milestone test week (P2 boundary):
docker run --rm -v "$PWD/data:/app/data" killswitch-pipeline \
    -m src.bgp ribs --window test_week
docker run --rm -v "$PWD/data:/app/data" killswitch-pipeline \
    -m src.bgp events --window feb2026_onset
```
Sanity checks: visibility ≈ 0.9–1.0 for major ASes on 2026-02-25/26,
collapsing near 0 on 02-28; the events file should show a dense wave of
withdrawals at the onset. Then validate against RIPEstat (Stage 4) before
any full run.

**Run it fully (only after the test week agrees with RIPEstat):**
```bash
docker run --rm -v "$PWD/data:/app/data" killswitch-pipeline -m src.bgp ribs
docker run --rm -v "$PWD/data:/app/data" killswitch-pipeline -m src.bgp events
```
The full RIB run covers the whole study period at 8h resolution — expect
hours-to-days and tens of GB. It is resumable: completed snapshots/windows
are skipped, so a crash or Ctrl-C loses at most one snapshot; just re-run
the same command. Collector list and windows live in `config/phases.yaml`.

## Stage 3 — IODA signals (`src/ioda`)

**What it does:** pulls BGP / active-probing / darknet signals for
`country/IR` and every ASN in the population →
`data/ioda/country_IR.parquet`, `data/ioda/asn/{asn}.parquet`.

**Test it:**
```bash
# country-level only, one week — a handful of requests:
.venv/bin/python -m src.ioda --window test_week --country-only
.venv/bin/python -c "import pandas as pd; df = pd.read_parquet('data/ioda/country_IR.parquet'); print(df.groupby('datasource').size()); print(df.head())"
```
Sanity checks: three datasources present; values collapse around 2026-02-28.
If the request 404s, the IODA API host has moved again — check the current
docs and fix `ioda_api_base` in `config/sources.yaml` (the brief warns
about this).

**Run it fully:**
```bash
.venv/bin/python -m src.ioda        # or: make ioda
```
Pulls the full study period for the country plus every ASN, rate-limited
(1 req/s, configurable in `phases.yaml`). Hundreds of ASNs × 3 signals takes
a while; it is resumable — already-fetched entities are skipped, so re-run
freely. Delete a parquet to force a re-fetch of that entity.

## Stage 4 — RIPEstat validation (`src/ripestat`)

**What it does:** fetches routing history for the sample ASNs
(`ripestat_sample_asns` in `phases.yaml`) → `data/ripestat/{asn}.json`,
then compares against the Stage 2 visibility series and writes
`outputs/ripestat_comparison.csv` flagging every disagreement.

**Test it:**
```bash
make ripestat            # a few small API calls
python3 -c "import json; d=json.load(open('data/ripestat/49666.json')); print(d['data']['query_starttime'], len(d['data']['by_origin']))"
```

**Run it fully (needs Stage 2 output):**
```bash
make ripestat-compare
```
Read the log: it prints per-ASN agreement counts. **Disagreements on the
sample ASNs mean Stage 2 is not yet trustworthy — investigate before any
full-period run.** Widen the sample by editing `ripestat_sample_asns`.

## Stage 5 — Analysis tables (`src/analysis`)

**What it does:** joins stages 1–3 into the four figure-ready tables under
`outputs/` (`visibility_by_type`, `bgp_vs_ioda`, `upstream_transitions`,
`event_speed`).

**Test it:**
```bash
.venv/bin/python -m pytest tests/test_states.py -v      # state-derivation logic
# then, with test-week data on disk:
.venv/bin/python -m src.analysis --only bgp_vs_ioda
.venv/bin/python -c "import pandas as pd; df = pd.read_parquet('outputs/bgp_vs_ioda.parquet'); print(df['state'].value_counts())"
```
Sanity check for the test week: states flip from `announced_and_reachable`
to `withdrawn` (mass withdrawal) across 2026-02-27/28.

**Run it fully:**
```bash
make analysis
```
Rebuilds all four tables from whatever stage outputs exist. Cheap and
idempotent — re-run after any upstream stage gains data. `event_speed`
needs the events for nov2019 / jun2025 windows too if you want the H4
comparison across events.

---

## Milestone 1, end to end

```bash
make test                                    # unit tests green
make population                              # Stage 1
make docker-image
docker run --rm -v "$PWD/data:/app/data" killswitch-pipeline -m src.bgp ribs --window test_week
docker run --rm -v "$PWD/data:/app/data" killswitch-pipeline -m src.bgp events --window feb2026_onset
.venv/bin/python -m src.ioda --window test_week
make ripestat
.venv/bin/python -m src.analysis --only bgp_vs_ioda
make ripestat-compare                        # must agree on the sample ASNs
```

(`make test-week` runs the same sequence with the venv interpreter — use it
if pybgpstream is installed locally instead of via Docker.)

**Definition of done:** population files exist, one week of visibility data
and the `bgp_vs_ioda` join exist, and `outputs/ripestat_comparison.csv`
shows agreement on the sample ASNs.

## Operational notes

- Every stage logs to **stderr** (ISO 8601 UTC) and writes only under
  `data/` or `outputs/`; storage timestamps are unix seconds UTC.
- Everything is resumable; the unit of loss on a crash is one snapshot /
  window / entity. Re-run the same command.
- All dates, windows, collectors, sample ASNs and thresholds live in
  `config/phases.yaml` — phase boundaries are hypotheses; revise them there,
  never in code.
- `data/` is gitignored **except** `ir_asn_classification.csv` (hand-curated
  — commit it). `outputs/` is fully gitignored.
