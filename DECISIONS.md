# DECISIONS.md — Analytical decision log

## Purpose and rules

This file records every methodological choice that could affect results. It exists because
post-hoc justification of analytical parameters is the failure mode this study cannot afford:
the methods section will be written from this log, and reviewers must be able to see that
each choice was made before, not after, seeing its effect on the findings.

Rules (binding on humans and on Claude Code alike):

1. **No silent parameters.** Any threshold, cutoff, exclusion, accounting rule, or definition
   used in analysis code must correspond to an entry here. If code needs a value that has no
   entry, the correct action is to propose an entry (status: PROPOSED) and stop — not to pick
   a value and continue.
2. **Decisions are append-only.** A decision is never edited or deleted once DECIDED. If it
   must change, add a new entry that supersedes it, with the reason. The history of changed
   minds is part of the record.
3. **Rationale before results.** The rationale field must be justifiable without reference to
   which hypothesis the value favors. "Chosen because it made the H3 separation clearer" is
   exactly what this log exists to prevent; "chosen to match the definition in [prior study]"
   or "median of the P0 distribution" is what it exists to record.
4. **Every DECIDED entry names where it is implemented** (config key or module) so the log and
   the code cannot drift apart.
5. **Robustness obligations are part of the decision.** If a value is somewhat arbitrary, the
   entry must name the alternative values under which results will be re-run and reported.

Statuses: `OPEN` (identified, not yet resolved) → `PROPOSED` (candidate value + rationale,
awaiting sign-off) → `DECIDED` (in force; implemented) → `SUPERSEDED by D-xxx`.

Entry template:

```
## D-0xx — <short title>
- Status: OPEN | PROPOSED | DECIDED (YYYY-MM-DD) | SUPERSEDED by D-0xx
- Question:
- Decision:
- Rationale:
- Alternatives considered / robustness checks owed:
- Implemented in: (config key / module / n.a.)
- Affects: (H1/H2/H3/H4, figures, tables)
```

---

## D-001 — Phase boundary dates
- Status: SUPERSEDED by D-025
- Question: Exact UTC timestamps for the P0/P1, P1/P2, P3/P4 boundaries. Press-reported dates
  (late Dec 2025; 28 Feb 2026; 25–26 May 2026) are priors, not answers.
- Decision: —
- Rationale to apply: boundaries must be set from the country-level IODA + aggregate BGP
  figure (the first figure produced), before any hypothesis-specific analysis is run, and then
  frozen in `config/phases.yaml`.
- Robustness owed: ±24h sensitivity on the P1/P2 boundary for the H4 onset-duration metric.
- Implemented in: `config/phases.yaml`
- Affects: everything downstream.

## D-002 — Definition of "full-feed peer" and visibility denominator
- Status: DECIDED (2026-07-03)
- Condition attached at sign-off (binding): item 6 (RouteViews-only collector set) is
  temporary scaffolding for milestone-1 validation only. Before ANY full-period run, the RIS
  question must be resolved by a new decision entry — either RIS backfill via direct
  data.ris.ripe.net bview fetch (bypassing the broker), or an explicitly documented
  RouteViews-only limitation with its H2/H3 sensitivity implications (path diversity;
  late-biased restoration timestamps under selective P4 propagation). Launching a full-period
  run without that entry violates this decision.
- Question: Which RIS/RouteViews peers count toward the visibility fraction, and how the
  denominator is computed per timestamp (peers reporting at that snapshot, not the static
  peer list — a collector outage must not read as an Iranian event).
- Motivating incident (2026-07-02/03 test-week run): the BGPStream broker has real gaps in
  RIS RIB metadata during the study period — zero rrc00 bviews indexed for Dec 2025–Mar 2026
  (verified directly against the broker API; the files exist on data.ris.ripe.net but are not
  served), and rrc12 coverage only resumes 2026-03-01. Consequently our "good" test-week
  snapshots were silently RouteViews-only (118 peers), and the Mar 1+ snapshots mixed in a
  partially-transferred rrc12 dump that truncated the combined stream (45M of ~101M elems)
  and shifted the full-feed denominator — a fake visibility discontinuity at exactly the
  P2→P3 transition. Exactly the artifact class this entry exists to prevent.
- Proposed decision:
  1. Full-feed qualification: per-snapshot and per-family; a peer (collector, peer_asn,
     peer_addr) qualifies if its RIB contributes >= 400,000 IPv4 routes (IPv4 metrics) or
     >= 50,000 IPv6 routes (IPv6 metrics). Values already in `config/phases.yaml`
     (`bgp.full_feed_min_prefixes`).
  2. Denominator: the count of qualifying peers observed at that snapshot (dynamic), never a
     static list.
  3. Snapshot validity rule: a snapshot parquet is written only if (a) the underlying stream
     terminated without transport errors and (b) every collector configured for that run
     contributed >= 1 full-feed peer. Violations abort the snapshot (file not written, run
     exits nonzero) rather than degrade silently.
  4. Auditability: each snapshot parquet records per-collector full-feed peer counts, so
     composition changes are mechanically detectable across the series.
  5. Constant-composition rule: any analysis comparing visibility across time uses a single
     fixed collector set for the whole compared range; that set is recorded in config per
     analysis window.
  6. Operational consequence for milestone 1: the test-week run uses
     collectors = [route-views2, route-views.linx] — the maximal set with continuous broker
     coverage across 2026-02-25→03-03 — giving a consistent ~118-peer base. RIS backfill by
     fetching bview files directly from data.ris.ripe.net (bypassing the broker) is a
     separate enhancement to evaluate before the full-period run, since broker RIS gaps span
     P1/P2.
- Rationale: (1)+(2) follow this entry's own framing (vantage-point artifacts); (3)–(5) make
  collector composition an invariant instead of a confounder; (6) is forced by measured
  broker coverage, chosen without reference to any hypothesis (RouteViews-only is simply the
  only complete set available for the window).
- Alternatives considered / robustness checks owed: static peer list (rejected, per above);
  proceed-with-subset-on-failure (rejected: silent degradation is the observed failure mode);
  full-feed IPv4 threshold 600k as robustness rerun; once RIS backfill exists, recompute the
  test week with RouteViews+RIS and compare visibility series.
- Implemented in: `src/bgp/ribs.py` (guard, audit column), `src/bgp/stream.py` (transport-
  error detection), `config/phases.yaml` (`bgp.rib_collectors` — new key scoping this
  decision to RIB/visibility runs; `bgp.collectors` continues to govern update-stream event
  pulls, which are unaffected by the broker's RIB metadata gaps; `bgp.full_feed_min_prefixes`).
  Note: collector lists live in phases.yaml, not sources.yaml as originally guessed above.
- Affects: every visibility number; H1–H4.

## D-003 — More-specifics accounting rule
- Status: SUPERSEDED by D-022
- Question: How visibility of a delegated block is computed when announcements are more- or
  less-specific than the delegation (critical in P4, where restoration may occur via /24s
  inside delegated /16s).
- Decision: —
- Alternatives: (a) max visibility over any covering/covered announcement; (b) address-space-
  weighted share of the delegated block covered by visible announcements. (b) is more honest
  about partial restoration; (a) is simpler and matches "is any of it back".
  Candidate: use (b) as primary, (a) as robustness.
- Implemented in: `src/common/` radix accounting
- Affects: H1 state derivation, H3 restoration metrics.

## D-004 — Per-AS state derivation thresholds (reachable / dark / withdrawn)
- Status: SUPERSEDED by D-013
- Question: The visibility fraction below which an AS counts as "withdrawn", and the active-
  probing level (relative to own P0 baseline) below which an announced AS counts as "dark".
- Decision: —
- Robustness owed: report state time-shares under at least two threshold pairs.
- Implemented in: `src/analysis/` state derivation, `config/phases.yaml` or dedicated config
- Affects: H1 (this is H1's core measurement).

## D-005 — IODA baseline adequacy and AS exclusion rule
- Status: SUPERSEDED by D-013
- Question: Minimum P0 active-probing signal for an AS to be interpretable; ASes below it are
  excluded from probing-based metrics (not from BGP metrics). Rule must be stated as a formula
  over P0 data, and the excluded list published.
- Decision: —
- Implemented in: `src/ioda/`
- Affects: H1; sample size reported in methods.

## D-006 — Restoration event definition (H3)
- Status: SUPERSEDED by D-023
- Question: The event marking a prefix "restored": first timestamp after the P4 boundary where
  visibility re-crosses X% of that prefix's own P0 baseline.
- Decision: —
- Candidate: X = 50 as primary; 25 and 80 as pre-committed robustness runs. Additionally
  report steady-state visibility (mean over final study month, relative to P0) as the
  completeness metric, separate from timing.
- Implemented in: `src/analysis/` survival prep
- Affects: H3 (centerpiece figure).

## D-007 — AS classification scheme and validation
- Status: SUPERSEDED by D-018
- Question: The type taxonomy (state_telecom, mobile, isp, government, financial, hosting,
  education, other), coding rules for ambiguous cases (e.g. state-owned ISPs serving
  consumers), and the inter-coder validation protocol (sample size, agreement statistic).
- Decision: —
- Rule already in force: `data/population/ir_asn_classification.csv` is hand-curated,
  versioned, never programmatically overwritten.
- Implemented in: the CSV + a coding-rules appendix
- Affects: H3 entirely.

## D-008 — Control population
- Status: SUPERSEDED by D-014
- Question: The set of non-IR ASes (candidate: 20–30 from TR, AE, PK) used to distinguish
  measurement-infrastructure artifacts from Iranian events. Selection rule must be stated
  (e.g. matched roughly on size and region) and fixed before event analysis.
- Decision: —
- Implemented in: `config/phases.yaml` or `config/controls.yaml`
- Affects: validity of every anomaly claim.

## D-009 — Flap definition (H4 "cleanliness")
- Status: DECIDED (2026-07-07, FF signed)
- Question: What counts as a flap during an onset window: a withdrawal followed by
  re-announcement of the same prefix within T seconds, from the same origin. Value of T.
- Method: computed the actual withdraw-then-reannounce gap for every BGP
  peer SESSION (prefix, origin asn, peer_asn - the level flapping is
  conventionally defined at, not a peer-agnostic "any withdraw anywhere
  followed by any announce anywhere," which would confuse ordinary
  cross-peer propagation-lag differences for a flap) across all 4 completed
  event windows (nov2019, jun2025, feb2026_onset, may2026_restoration;
  jan2026_event pending). 12,772,856 withdraw->reannounce gaps total.
  `src/analysis/flap_gaps.py::withdraw_reannounce_gaps`, 6 tests.
- Data shape (honest finding, not a clean D-013-style bimodality valley -
  this is a continuous, heavy-tailed, multi-modal gap distribution, not a
  bounded ratio, so that method doesn't transfer cleanly):
  - 25.1% of gaps are 0s (same-instant withdraw+reannounce - almost
    certainly a single sub-second update burst, not two real events).
  - A sharp initial spike 0-10s (39.3% of all gaps combined), decaying
    through 10-30s, THEN RISING AGAIN to a local secondary peak at 30-60s
    (8.3%) - consistent with (not verified against a citation - this is an
    observation, not an imported fact) typical BGP MRAI (minimum route
    advertisement interval) timers, commonly ~30s.
  - A THIRD, smaller local peak at 600-1200s / 10-20min (8.6% combined) -
    consistent with (same caveat) classic BGP route-flap-damping
    suppress/reuse timer conventions.
  - Pattern holds across all 4 windows individually (nov2019 has the
    largest 10-20min bump at 16.1%, plausibly reflecting less-provisioned
    2019-era infrastructure/longer reconvergence; the other 3 windows show
    2-7%): share of gaps <=60s ranges 52.8%-70.0% per window, median gap
    12-37s per window.
  - Percentiles (all windows combined): p25=0s, p50=29s, p75=781s (13min),
    p90=5838s (97min), p95=62209s (17.3h), p99=401108s (4.6 days).
- Decision: **T = 60 seconds** (FF signed off in chat, 2026-07-07). Rationale:
  60s sits right at the boundary between the sharp initial 0-60s decay
  (almost certainly single-update-burst / sub-minute protocol-level
  retransmission artifacts, not meaningful reannouncement dynamics) and the
  distribution's later, much more gradual/multi-modal structure - it is the
  most defensible single cut point given the data doesn't offer a clean
  valley, not a value picked for convenience or to favor either hypothesis.
- **Robustness result (2026-07-07):** re-ran H4 (`event_speed`) with
  T in {none/unfiltered, 30s, 60s, 300s} across all 4 completed event
  windows. D-024's primary cross-window metric, `duration_p5_p95_s`, is
  essentially unchanged across every threshold (all within ~2%;
  may2026_restoration identical to the second at 58,420s in all four runs;
  feb2026_onset 151,364s unfiltered vs 151,288s at every filtered level).
  `n_prefixes_withdrawn` moves only marginally (largest change
  feb2026_onset 6983->6415, ~8%, then flat across 30/60/300s). The
  cross-window qualitative comparison this decision exists to protect is
  robust to the exact choice of T within the tested range. One real
  exception, flagged rather than smoothed over: `duration_p50_s` for
  may2026_restoration shifts materially with filtering (41,505s unfiltered
  -> 60,601s at T=60s/300s, ~46% later) - flap withdrawals were
  concentrated early in that window's distribution, so removing them
  shifts the median onset timing notably even though the p5-p95 range
  itself doesn't move. `duration_p50_s` is a secondary/contextual metric,
  not D-024's primary comparator, but any prose citing it for
  may2026_restoration specifically should use the T=60s (post-flap-filter)
  value, not the unfiltered one.
- Alternatives considered: a bimodality-valley method matching D-013
  (rejected for this specific variable - gap-time is an unbounded,
  heavy-tailed continuous quantity, not a bounded ratio/fraction, and the
  actual histogram does not show one clean valley, only a decaying spike
  followed by two smaller secondary bumps); a literature-standard flap-
  damping constant (not used - would require a verified citation before
  going in the paper per CLAUDE.md's citation rule, and no such citation
  has been sourced/verified yet; the BGP-timer correspondences noted above
  are offered as plausible mechanism, not as an imported fact).
- Implemented in: `src/analysis/flap_gaps.py` (`withdraw_reannounce_gaps`,
  `flap_withdrawal_mask`, `drop_flap_withdrawals`); wired into
  `src/analysis/joins.py::event_speed` (`flap_threshold_s` param, default
  None preserves pre-D-009 behavior) via `config/phases.yaml`
  (`analysis.flap_threshold_s: 60`, `analysis.flap_threshold_robustness_s:
  [30, 300]`); `src/analysis/__main__.py` passes the config value through.
  16 tests total (`tests/test_flap_gaps.py`, `tests/test_joins.py`).
- Affects: H4 comparison table (`event_speed.parquet`, now flap-filtered
  by default in the real pipeline run).

## D-010 — Onset duration metric (H4)
- Status: SUPERSEDED by D-024
- Question: "Time from first to last withdrawal" is sensitive to stragglers; decide between
  full range and an interpercentile range (e.g. 5th–95th percentile of withdrawal times
  across the affected population), applied identically to 2019, June 2025, and Feb 2026.
- Decision: —
- Candidate: interpercentile as primary, full range reported alongside.
- Implemented in: `src/analysis/` event metrics
- Affects: H4.

## D-011 — Attribution tier assignment rule
- Status: DECIDED (pre-registered by study design)
- Question: How empirical claims in the paper are tiered.
- Decision: Three tiers, applied per sentence: **observed** (directly present in measurement
  data), **strongly implied** (measurement pattern whose alternative explanations are
  implausible given tight temporal ordering and at least one independent corroborating
  source), **consistent with reporting** (plausible interpretation relying on external
  reports; the data does not independently establish it). Causal language about actors
  (government orders, ministry decisions) can never exceed tier 3 on measurement data alone.
- Rationale: attribution discipline is a design commitment of the study, not a parameter.
- Implemented in: `CLAUDE.md` writing rules; corroboration table in the paper
- Affects: all prose.

## D-012 — RIS backfill scope and the two-series design
- Status: DECIDED (2026-07-03)
- Question: How RIS collectors re-enter the dataset given the BGPStream broker's RIB
  metadata gaps (see D-002 motivating incident), and which analyses may use RIS-inclusive
  data. This entry discharges the condition attached to D-002 at sign-off.
- Proposed decision:
  1. Primary visibility series: RouteViews collectors (route-views2, route-views.linx),
     uniform 8h grid over the full study period. All primary H1-H4 metrics — including
     D-006 restoration events, which compare P4 visibility to each prefix's own P0
     baseline — are computed on this series alone, satisfying D-002's constant-composition
     rule without a 14-month RIS backfill.
  2. RIS backfill (rrc00, rrc12) by direct fetch of bview files from data.ris.ripe.net
     (deterministic URL scheme; bypasses the broker), processed through the identical
     pipeline (same D-002 guards; per-collector audit columns), for three ranges only:
     (i) the P2 onset window (test-week range, 2026-02-25 -> 03-03),
     (ii) all of P4 (2026-05-24 -> study end),
     (iii) one P0 reference month (2025-09-01 -> 10-01, chosen as a quiet baseline month
     away from the June 2025 war blackouts) to give the RIS-inclusive series its own
     like-for-like baseline.
  3. The RIS-inclusive series feeds pre-specified secondary analyses only: H2 upstream
     identification detail, and an H3 selectivity cross-check (prefixes visible at RIS
     peers but not RouteViews peers during P4 = evidence of regionally selective
     re-announcement). It is never mixed with the primary series within a single
     comparison.
  4. Robustness: restoration timestamps computed on both series for the P4 overlap;
     divergences reported in the paper, not silently reconciled.
- Rationale: preserves a single internally consistent primary series (D-002 rule 5);
  adds vantage diversity exactly where it changes conclusions (transition windows);
  avoids building 14 months of backfill for months where RouteViews-only measurement is
  uncontroversial. Scope chosen by phase structure, not by any hypothesis's outcome.
- Alternatives considered / robustness checks owed: full-period RIS backfill (rejected:
  cost without corresponding inferential gain outside transitions; revisit if secondary
  analyses reveal primary-series blind spots); RIS-only (rejected: single-operator
  artifact risk — the exact failure mode of the D-002 incident — and loss of
  cross-regional contrast needed for the H3 selectivity check).
- Implemented in: `src/bgp/` (direct-fetch data source), `config/phases.yaml`
  (backfill ranges), same guards as D-002.
- **Robustness exhibit BUILT (2026-07-07)**: [[paper-two-series-justification]]
  (FF-approved methods argument) called for one figure demonstrating, not
  just asserting, that visibility is bimodal enough for a threshold choice
  to be insensitive to which series is used. `src/analysis/series_comparison.py`
  (`visibility_distribution_comparison`, `bimodality_summary`) compares the
  two series at their shared, non-degraded snapshots (never merged).
  Result: primary series 98.56% of values near 1.0, 0.83% near 0.0, only
  0.62% in the ambiguous [0.1, 0.9] middle; RIS-secondary 98.37%/1.05%/0.59%
  respectively - nearly identical shape despite one series having ~118
  observers and the other ~380. `outputs/visibility_bimodality_comparison.parquet`
  (4,786,807 rows, raw values for the histogram figure) +
  `outputs/visibility_bimodality_summary.parquet` (the numbers above). 4 tests
  (`tests/test_series_comparison.py`).
- Affects: H2, H3 (secondary analyses); primary series unaffected.

## D-013 — Resolution of D-004 (state thresholds) and D-005 (probing baseline)
- Status: DECIDED (2026-07-03)
- Question: Concrete rules for the OPEN entries D-004 and D-005, needed before any H1
  state share is reportable. Motivated by the milestone-1 join: with no baseline defined,
  announced_but_dark cannot fire by construction (derive_state requires positive evidence
  of darkness), so the milestone outputs/bgp_vs_ioda.parquet is plumbing-valid but not
  analysis-grade. Raw signals confirm the state exists (e.g. 2026-02-28 16:00: AS44244
  probing = 0.0, AS197207 probing = 4, both at visibility 1.0).
- Decision (what is signed off is the PROCEDURE; numeric thresholds in (3) are explicitly
  provisional pipeline values until steps (4)-(5) replace them):
  1. (D-005) Probing baseline: per AS, the median of the IODA active-probing signal over
     the fixed P0 reference window 2025-09-01 -> 2025-10-01 (the same quiet month D-012
     uses, chosen before results for the same reason: distance from the June 2025 war
     blackouts and from P1 onset).
  2. (D-005) Adequacy/exclusion rule: an AS enters probing-based metrics only if its P0
     reference-window signal has >= 50% nonzero time-bins AND median >= 5 signal units;
     excluded ASes are listed in a published table and remain in BGP-only metrics.
     Robustness: rerun with median >= 2.
  3. (D-004, provisional) visibility_announced_min = 0.5; probing_dark_ratio = 0.2. These
     unblock pipeline development; no H1 number computed with them is paper-grade.
  4. (D-004, final visibility threshold) Set from the data's own structure: plot the P0
     distribution of per-AS visibility; expected strongly bimodal. Final threshold placed
     in the empty valley between modes, with the histogram published and threshold-
     insensitivity across the valley demonstrated. A literature check for precedent
     definitions (prior shutdown measurement studies, IODA methodology) runs first; a
     precedent threshold, if found and verifiable, takes priority for comparability.
     Citations verified at that time — nothing cited from memory.
  5. (D-004, final dark ratio) Calibrated on data outside the analysis: using the D-008
     control population in quiet periods, choose the largest ratio whose false-dark rate
     is < 1%. (This makes deciding D-008 a prerequisite; D-008 priority raised.)
  6. Robustness grid (pre-committed regardless of final values): state time-shares
     reported under (visibility threshold ±0.25) x (dark ratio 0.1, 0.3).
- Rationale: procedure over naked numbers — each final value is either inherited from
  verifiable precedent, derived from the P0 distribution's structure, or calibrated on
  non-analysis data; none is hand-picked against the hypotheses.
- Supersedes: D-004, D-005 (both OPEN -> resolved by this entry's procedure).
- Implemented in: `config/phases.yaml` (`analysis.*` incl. new `probing_baseline_window`,
  `probing_adequacy`), `src/analysis/joins.py` + `states.py`, `src/ioda/` (--baseline pull
  into data/ioda/baseline/).
- Affects: H1 entirely (state shares are H1's core measurement); H3 secondarily.

## D-014 — Resolution of D-008: control population
- Status: DECIDED (2026-07-03)
- Question: The fixed set of non-IR ASes used to distinguish measurement-infrastructure
  artifacts from Iranian events (resolves D-008), now blocking two things: the artifact
  check on the H1 announced-but-dark finding, and the D-013 dark-ratio calibration.
- Proposed decision:
  1. Control countries: TR, AE, PK (per the study brief: regional neighbors sharing
     transit ecosystems and latency paths, with no *documented nationwide* shutdown
     during the study period; documented regional/partial events — e.g. exam-window or
     protest-related local shutdowns — are recorded in a caveats table with dates, and
     affected bins are excluded from calibration but kept in artifact checks).
  2. Mechanical selection rule (no hand-picking): per country, the 10 ASNs with the
     largest delegated IPv4 address space (from the RIR delegation files — RIPE NCC for
     TR/AE, APNIC for PK, added to Stage 1) that pass the identical D-013 probing-
     adequacy rule over the same Sept 2025 reference month. 3 x 10 = 30 control ASNs,
     frozen in `config/controls.yaml` before any control-based conclusion is drawn.
  3. Artifact criterion: an Iranian anomaly (probing collapse, visibility drop, state
     transition wave) is treated as a measurement artifact if the same-signed anomaly
     appears in >= 10% of control ASNs in the same time bin. Artifact-flagged bins are
     excluded and reported.
  4. Dark-ratio calibration (per D-013 step 5): on control ASNs in quiet periods, choose
     the largest ratio with false-dark rate < 1%.
  5. Usage: control aggregates plotted alongside IR in every headline figure; every
     event/anomaly finding names its control-check result (per the repo-level rule).
  6. Robustness owed: repeat key artifact checks with (a) the next-10 ASNs per country,
     (b) leave-one-country-out.
- Operational implications (why this should be decided before the full-period run):
  BGP-side control visibility requires control prefixes in the radix matcher at
  stream time — deciding after the full-period run would force a full reprocess (~4
  days). The immediate H1 artifact check is cheaper: it needs only IODA pulls for the
  30 control ASNs (test week + baseline month, ~1-2 h), no RIB reprocessing.
- Rationale: selection is mechanical (size rank + identical adequacy rule), fixed before
  event analysis, and matched on region/size per D-008's own framing; the 10% artifact
  threshold is provisional pipeline machinery subject to the same robustness reporting
  as D-013 values.
- Supersedes: D-008 (OPEN -> resolved by this entry).
- Implemented in: `config/controls.yaml` (frozen ASN list), `src/population/` (APNIC
  delegation source, control population files), `src/common/prefixmatch.py` usage in
  Stage 2 (tag matched prefixes IR vs control), `src/ioda/` (control pulls),
  `src/analysis/` (control comparison module).
- Affects: validity of every anomaly claim (H1-H4); D-013 final dark ratio.

## D-015 — Amendment to D-012: P3 sample slices added to the RIS backfill
- Status: DECIDED (2026-07-03)
- Question: Whether the RIS-inclusive secondary series should cover any of P3. D-012
  scoped the backfill to transitions on the expectation that the plateau was static.
  The milestone-1 H1 result (announced_but_dark as the dominant P2/P3 state, with the
  Mar 1 cosmetic re-announcement wave) elevates "announced" during P3 to a core claim
  with a vantage-sensitive failure mode: selective (e.g. regional) re-announcement
  could make RouteViews-only measurement mis-state announcement levels for the whole
  plateau.
- Decision: add three one-week P3 sample slices to `bgp.ris_backfill.ranges`, chosen by
  calendar rule (the 14th 00:00 UTC to the 21st 00:00 UTC of each full P3 month: March,
  April, May 2026; ~63 snapshots). Purpose: verify RIS/RouteViews agreement on
  announcement levels through the plateau. If they diverge beyond the D-002 audit
  tolerances, widen coverage via a further entry.
- Rationale: slice dates fixed by calendar rule before any RIS P3 data has been seen;
  the trigger is a vulnerability identified in the finding's logic, not the finding's
  direction.
- Implemented in: `config/phases.yaml` (`ris_backfill.ranges.p3_sample_*`),
  `src/bgp/backfill.py` (`--range` scoping for parallel workers).
- Affects: H1 plateau claims; D-012 secondary-series scope.

## D-016 — Control-prefix derivation and Stage 2 population tagging (completes D-014)
- Status: DECIDED (2026-07-04, signed off by FF)
- Question: D-014 requires control-country prefixes in the Stage 2 radix matcher at
  stream time, tagged IR vs control, but does not pin (a) which prefixes constitute
  the control prefix set or (b) how the tag is carried in Stage 2 outputs.
- Proposed decision:
  1. Control prefix set: all delegated IPv4 and IPv6 blocks attributed — via the
     extended-delegation opaque-id — to the same organizations as the frozen control
     ASNs in `config/controls.yaml`, taken from the same RIR delegation files used
     for D-014 selection (RIPE NCC for TR/AE, APNIC for PK). Emitted once to
     `data/population/control_prefixes.csv` (columns: prefix, family, cc, org ASNs)
     alongside the frozen ASN list; regenerating requires the delegation snapshot
     date to be recorded.
  2. Tagging: Stage 2 outputs (RIB snapshots and event streams) gain a `cc` column
     (IR, TR, AE, PK) set from which population tree the announced prefix matched.
     Downstream IR-only series filter `cc == "IR"`; control series group by `cc`.
  3. Overlap rule: IR and control delegations are disjoint address space, so a
     prefix matching both trees indicates a data error — the run aborts (same
     spirit as D-002: fail loudly, never guess).
- Rationale: mirrors the Stage 1 IR derivation exactly (delegation-based, same
  source files), and attributes address space to organizations by the identical
  opaque-id rule already frozen in D-014 — no new discretion is introduced. The
  alternative (per-ASN announced-prefix lists, e.g. from RIPEstat) was rejected
  because it derives the population from BGP itself — circular for a study whose
  measured variable is BGP visibility — and is snapshot-dependent and asymmetric
  with the IR side.
- Robustness owed: (a) report per-country matched-prefix counts next to IR's so
  gross size mismatch is visible; (b) the D-014 next-10 robustness set reuses this
  derivation unchanged; (c) control visibility findings report per-ASN (origin_asn)
  breakdowns so a single org's delegation quirks cannot drive an artifact verdict.
- Operational: implementing this changes the Stage 2 output schema; the test-week
  run must be re-validated before any full-period run (per the standing rule).
- Affects: D-014 artifact checks on BGP-side signals; every full-period Stage 2 run.
- Implemented in: `src/population/controls.py` (`--prefixes` emission +
  `control_prefixes.meta.json` snapshot record), `src/common/prefixmatch.py`
  (tagged populations, `PopulationOverlapError` guard), `src/bgp/ribs.py` +
  `src/bgp/events.py` (`cc` column; consolidation reads pre-D-016 snapshots as
  IR), `src/bgp/__main__.py` (control file required for primary ribs/events;
  ribs-ris stays IR-scoped per D-012), `src/analysis/__main__.py` +
  `src/analysis/joins.py` (IR-only filtering for current tables).

## D-017 — RIB snapshot acquisition: direct archive fetch primary, broker fallback
- Status: DECIDED (2026-07-04, approved by FF in session)
- Question: Which transport acquires RIB dump files for Stage 2 snapshots. The
  BGPStream broker path has produced two independent failure classes in one week:
  missing catalogue metadata (D-002 root cause) and deterministic mid-transfer
  failures on specific healthy files ("partial file (18)" / corrupted-record,
  reproduced 10+ attempts over 9+ hours on 5 distinct dumps across both local and
  EC2 hosts, while plain HTTP fetches of the same files complete and pass
  integrity checks). Meanwhile the D-012 direct-fetch path has served the entire
  RIS backfill (~460 MB/snapshot, hundreds of snapshots) with only ordinary
  download retries.
- Decision:
  1. RIB snapshots (primary series and D-012 secondary series): fetch dump files
     directly from the collector archives (deterministic URL schemes,
     archive.routeviews.org and data.ris.ripe.net), read via the singlefile
     interface. The broker becomes the fallback, tried only when a direct fetch
     fails (e.g. a collector skipped a dump at the grid time and the broker's
     catalogue may know a nearby one).
  2. Events/update streams: broker unchanged. Update windows span hundreds of
     small files per collector whose enumeration and time-ordered merge is
     exactly what the broker is for, and it has not failed there.
  3. Both transports parse the same archive files with the same underlying
     library; all D-002 validity guards (fatal record statuses, per-collector
     full-feed presence, audit column) apply identically regardless of transport.
- Robustness: the switch is validated by exact-equality comparison
  (src/analysis/compare_ribs_runs.py) between a direct-primary test-week run and
  the existing broker-produced test week: identical collector_fullfeed audits, IR
  prefix sets, and per-prefix visibility numbers are required before any
  full-period run. Transport is thereby shown to be measurement-invariant, not
  assumed.
- Affects: every Stage 2 RIB run from here on; unblocks the 4 RIS-backfill holes
  and the EC2 test-week snapshot that the broker path cannot transfer.
- Implemented in: `src/bgp/risfiles.py` (RouteViews URL scheme + fetch),
  `src/bgp/ribs.py` (direct-primary snapshot path with broker fallback),
  `src/bgp/backfill.py` (same flip for the secondary series),
  `config/sources.yaml` (`routeviews_archive_base`).

## D-018 — Resolution of D-007: AS classification taxonomy, coding rules, validation
- Status: DECIDED (2026-07-05, signed off by FF)
- Question: D-007 left open the type taxonomy, ambiguity rules, and validation
  protocol for `data/population/ir_asn_classification.csv` (H3 depends on it).
- Proposed decision:
  1. Taxonomy (8 types, as drafted in D-007): `state_telecom` (incumbent /
     backbone / international-gateway operators), `mobile` (mobile network
     operators), `isp` (fixed consumer/business access providers), `government`
     (non-commercial state bodies), `financial` (banks, payment processors,
     exchanges), `hosting` (datacenters, cloud, CDN), `education` (universities,
     research networks), `other`.
  2. Coding rules for ambiguity: (a) FUNCTION OVER OWNERSHIP — an AS is coded by
     the service it observably provides, not its shareholders; ownership goes in
     `notes` (a state-owned consumer ISP is `isp`). `state_telecom` is reserved
     for core-infrastructure operators regardless of corporate form. (b) An AS
     belonging to a conglomerate is coded by that AS's own role, not the group's
     breadth. (c) Mobile operators are `mobile` even when state-linked (H3 asks
     about service-class treatment). (d) Every coded row records `confidence`
     (high/medium/low) and `sources` (URLs consulted).
  3. Scope: code the top ~100 ASNs by delegated IPv4 space plus every ASN that
     appears in an H3-relevant cohort (always-reachable set, first-restored set);
     the long tail stays uncoded and is excluded from type-based analyses, with
     the classified share of IR address space reported alongside.
  4. Workflow honoring the hand-curation rule: Claude researches and writes
     PROPOSALS to `outputs/asn_classification_proposal.csv` (asn, org_name,
     proposed_type, confidence, sources, notes); FF reviews and merges approved
     rows into the protected CSV. The protected file is never written by code.
  5. Validation: FF independently codes a random sample of 40 proposal rows
     (stratified by address space) blind to the proposed types; report percent
     agreement and Cohen's kappa in the paper. If kappa < 0.7, revise coding
     rules and re-code before H3 runs.
- Rationale: function-over-ownership prevents the ownership question (interesting
  but separate) from contaminating the service-class question H3 actually asks;
  confidence + kappa make the subjectivity measurable instead of hidden;
  proposal-file workflow keeps the protected CSV hand-curated in fact, not just
  in name.
- Robustness pre-committed: H3 rerun excluding `confidence=low` rows; H3 rerun
  with `state_telecom` and `government` merged (the most plausible boundary
  dispute).
- Affects: H3 entirely; D-007 (superseded by this entry if decided).

## D-019 — Amendment to D-018: sector scope extension and two added types
- Status: DECIDED (2026-07-05, FF approved in session)
- Question: D-018's size-ranked scope (top-100 by delegated space + cohort
  members) excludes whole sectors that H3's whitelist hypothesis is about,
  because their networks are small (banks run /24s, not /16s).
- Decision:
  1. Scope extension by MECHANICAL NAME-MATCH against the registry org-name
     field (case-insensitive), recorded here; patterns only nominate candidates
     for coding — the coded type remains a per-row judgment, so over-broad
     patterns are harmless (e.g. an ISP matching "rasaneh" stays isp):
     - financial: bank|financ|payment|informatic|shaparak|bourse|exchange|insurance|bime
     - energy:    oil|gas|petro|energy|electric|power|tavanir|niroo|barq
     - media:     news|press|media|broadcast|rasaneh|khabar
  2. Taxonomy gains `energy` and `media` (10 types total). IRIB recodes from
     government to media.
  3. Candidates considered and REJECTED: `health` (Iranian medical
     universities administer the provincial health system — the
     education/health boundary is unresolvable by name, so such orgs stay
     education/government with sector noted), `transport`/`industry`
     (informative about the economy, not about shutdown policy; stay `other`
     with sector noted).
  4. Small-cell reporting rule (FF approved): any type with FEWER THAN 20
     classified members carries count-based claims only — no percentages, no
     shares — and every type-level H3 result reports its N. Sector cells are
     additionally expected to fail ping-adequacy (small networks), so their
     evidence is routing-side (announced/withdrawn) by construction; state
     this in methods.
- Rationale: sector inclusion is the analytically-motivated part of the H3
  scope and must not depend on network size; name-matching keeps the
  extension mechanical and reproducible; the two added types are the two
  whose H3 questions are sharp (critical-infrastructure whitelisting; state
  media continuity) and whose names are self-identifying.
- Robustness: cohort analyses (always-reachable, first-restored) re-run with
  and without extension rows; blind-validation sample redrawn over the
  extended proposal before FF codes it.
- Affects: D-018 scope and taxonomy; H3 sector-level claims.

## D-020 — Minimum peer-diversity rule for degraded primary RIB snapshots
- Status: DECIDED (2026-07-06, FF signed)
- Question: When a snapshot's full-feed peer count is sharply reduced by a short
  upstream archive dump, do its visibility estimates enter analysis, and under
  what rule? (D-002 makes the denominator dynamic, so such estimates are
  unbiased but high-variance; D-002 does not set a variance floor.)
- Motivating incident (2026-07-06, full-period run QC): 3 of 1,278 primary
  snapshots fail the ribs_health drift check (>15% from series median), all
  traced to short route-views.linx archive dumps (route-views2 stable at 23/0
  throughout; archive Content-Length for rib.20250616.0000 = 20.9MB vs ~150MB
  for neighbors). Regeneration reproduces them byte-identically — the loss is
  upstream at the collector, not in our transport. Affected (UTC):
  2025-05-27T00:00 (ff 49/22), 2025-06-06T00:00 (ff 47/20),
  2025-06-16T00:00 (ff 26/3). The last falls
  INSIDE the jun2025 war-blackout window, so silent inclusion or silent
  exclusion both risk shaping an H-relevant curve.
- Proposed decision:
  1. Per-snapshot, per-family full-feed counts (from the collector_fullfeed
     audit column) are carried into the consolidated visibility series at
     consolidation time (columns ff_v4, ff_v6).
  2. A (snapshot, address family) cell is DEGRADED if its full-feed count is
     below an absolute floor of 15 peers (config: analysis.min_fullfeed_peers).
     Degraded cells are excluded from visibility-based analyses for that family
     only; the other family stays in. Under this rule exactly one cell is
     excluded today: 2025-06-16T00:00 IPv6 (3 peers). The 8h-adjacent snapshots
     on both sides are healthy, so exclusion creates a one-bin gap, never a
     boundary shift.
  3. Rationale for 15: worst-case binomial s.e. of a visibility fraction at
     n=15 is ~0.13, small relative to the 0.5 announced-threshold band
     (D-013); at n=3 it is ~0.29 — indistinguishable from signal. The floor is
     deliberately absolute, not median-relative: a relative rule would flag
     healthy early-series snapshots if peering grows, and 26/51 sits exactly
     at a 50%-of-median knife edge (0.51) — a rule that flips on one peer is
     not robust.
  4. Alternatives considered and rejected: substituting the RIS secondary
     series at affected timestamps (violates D-012's never-mix rule);
     dropping the affected snapshots wholesale (discards a usable n=26 IPv4
     estimate inside the jun2025 window).
- Robustness pre-committed: (a) affected analyses rerun with degraded cells
  included — results must not flip; (b) degraded-cell estimates compared
  against linear interpolation of the adjacent healthy snapshots, reported if
  divergent; (c) floor swept over {10, 15, 20, 25} — the set of excluded cells
  and all downstream conclusions reported per value; (d) note that jun2025
  event-timing metrics (H4) come from update streams, not RIBs, and are
  untouched by this rule.
- Affects: consolidation schema (ff_v4/ff_v6 columns), analysis.min_fullfeed_peers
  in config, every visibility-based analysis; complements D-002.

## D-021 — Amendment to D-017: direct archive fetch extended to update streams
- Status: DECIDED (2026-07-06, FF signed)
- Question: D-017 point 2 scoped events/update streams to stay broker-only,
  on the stated grounds that "it has not failed there." That premise is now
  false: does direct-archive fetch (already D-017's fix for RIB dumps) need
  to extend to update streams too, and if so, how?
- Motivating incident (2026-07-06, jun2025 event window on EC2): the 15-day
  jun2025 events run hit `StreamTransportError` (collector rrc00,
  corrupted-record) 4 times across the full exponential retry ladder
  (60/120/240/480s, spanning ~3h wall-clock at different times of day), every
  attempt failing at the identical stream position (2025-06-11T21:14:21Z,
  after exactly 10,000,000 events) with the identical libcurl error
  ("Failure when receiving data from the peer (56)" / truncated gzip). I
  fetched the three candidate rrc00 update dumps directly from
  data.ris.ripe.net for that 15-minute span
  (updates.20250611.{2110,2115,2120}.gz, 12.8/10.5/17.1 MB) and verified all
  three with `gzip -t`: intact, correct size, no corruption. This is the same
  fingerprint as D-017's root cause (broker/wandio deterministically mangles
  specific healthy files in transit) — it just hadn't been observed on the
  updates path before because the study period's event windows are short and
  few, until jun2025 (15 days, the longest).
- Proposed decision: extend the D-012/D-017 direct-fetch mechanism to update
  streams. RIS update dumps follow a deterministic URL scheme
  (`data.ris.ripe.net/{collector}/{YYYY.MM}/updates.{YYYYMMDD}.{HHMM}.gz`,
  5-minute cadence) exactly analogous to the bview scheme already implemented
  in `src/bgp/risfiles.py`. Concretely: enumerate the update-file grid for
  the requested window per collector, fetch each directly (broker fallback
  on a missing/failed direct fetch, same as D-017 rule 1), replay through the
  singlefile interface. Scope: RIS collectors only (rrc00, rrc12 -
  `config.ris_backfill_collectors`, reused from D-012). RouteViews collectors
  (route-views2, route-views.linx) stay on the broker for updates, unchanged
  from D-017 - they have not failed there, and the observed incident is
  RIS-specific. Per-collector file sequences are fetched and replayed in
  chronological order but collectors are not globally merge-sorted against
  each other; this is safe because `process_window`'s withdrawal attribution
  keys are (peer_address, peer_asn, prefix), which do not cross collectors,
  and event_speed (H4) was independently verified order-independent.
  Falls back to the pre-D-021 broker-only path (all 4 collectors, full retry
  ladder) on any direct-fetch failure, mirroring D-017 rule 1.
- Robustness: same exact-equality standard as D-017, deferred to a live check
  rather than a synthetic one - the jun2025 window itself is the validation:
  if the direct-fetch rerun completes, its event counts/timing are compared
  against the two already-successful broker-fetched windows (nov2019,
  may2026_restoration) for plausibility (comparable per-day event rates, no
  A/W schema drift), since jun2025 has no independent broker-fetched ground
  truth of its own - that is the whole reason it needed this fix.
- Affects: jun2025 events window (was blocked, ladder exhausted); any future
  event window that hits the same RIS broker-side file corruption.
- Implemented in: `src/bgp/risfiles.py` (`update_url`, `fetch_update`,
  `read_update_file`), `src/common/timeutil.py` (`update_times`, 5-min grid),
  `src/bgp/events.py` (`process_window_direct`, `_iter_direct_ris`, direct-
  then-broker-fallback wiring in `run_events`), `src/bgp/__main__.py` (passes
  `ris_archive_base` and a dedicated cache dir). 102 tests green.

## D-022 — Resolution of D-003: more-specifics accounting rule
- Status: DECIDED (2026-07-06, FF signed)
- Question: How is visibility of a delegated block computed when observed
  announcements are more- or less-specific than the delegation (critical in
  P4, where restoration may occur via /24s inside delegated /16s)?
- Decision: primary metric is address-space-weighted coverage: for a
  delegated block, visibility = (sum of address space of covered observed
  announcements that are "seen," i.e. carried by a full-feed peer, weighted
  by each covered chunk's own size) / (total address space of the delegated
  block). Robustness companion: max-visibility-over-any-covering-or-covered-
  announcement ("is any of it back") reported alongside, never replacing the
  primary metric.
- Rationale: address-space-weighted coverage is the only one of the two
  candidates that can distinguish "the whole /16 came back" from "a single
  /24 inside it came back" - exactly the P4 restoration question this entry
  exists for. Max-visibility answers a real but coarser question ("has
  anything at all reappeared") and is kept as a companion metric so a reader
  can see both without re-deriving one from the other.
- Alternatives considered: max-visibility as primary (rejected - too coarse
  for P4, would read a single restored /24 identically to a fully restored
  /16); a strict announcement-count (not space-weighted) share (rejected -
  weights a /24 and a /16 equally, which misstates how much address space
  is actually reachable).
- Robustness owed (pre-committed, not yet run): recompute H3/H1 P4 numbers
  under both metrics and report both; spot-check the always-reachable cohort
  (state gateway + CDN/hosting ASNs, see [[asn-classification-logic]]-era
  H3 leads) for cases where the two metrics disagree, since a disagreement
  there is the most H3-relevant failure mode.
- Implementation status: BUILT (2026-07-07). `src/common/rollup.py::rollup_visibility`
  computes address-space-weighted visibility per delegated block, plus the
  `visibility_max` companion. Found and fixed a real correctness bug during
  implementation: real routing tables commonly announce a block AND
  more-specifics inside it simultaneously (deaggregation for traffic
  engineering) - naively summing size(p)*visibility(p) over every observed
  prefix covered by a block double-counts that overlapping space (verified:
  some blocks' P0 baseline came out above 1.0, impossible for a fraction).
  Fixed via longest-prefix-match resolution (an address covered by several
  nested announcements is attributed only to the most specific one) -
  `src/common/rollup.py::_seen_space`, regression-tested against the actual
  overlapping case found in the data. All H1/H3 numbers computed before
  2026-07-07 used per-observed-prefix visibility, not this rule, per the
  note below (unaffected qualitatively; P4/H3 restoration numbers now use
  this rollup as of D-023's implementation).
- Implemented in: `src/common/rollup.py` (`rollup_visibility`, `map_to_blocks`,
  `_seen_space`); tests in `tests/test_rollup.py`.
- Affects: H1 state derivation (marginally, mostly stable), H3 restoration
  metrics (materially, this is what P4 completeness claims need).

## D-023 — Resolution of D-006: restoration event definition (H3)
- Status: DECIDED (2026-07-06, FF signed)
- Question: What event marks a prefix "restored"?
- Decision: the restoration timestamp for a prefix is the first ts after the
  P4 boundary at which its visibility (per D-022's address-space-weighted
  metric once built; per-observed-prefix visibility until then) re-crosses
  50% of that prefix's own P0 baseline mean. 25% and 80% are pre-committed
  robustness thresholds, run and reported alongside, not substituted in.
  Steady-state visibility (mean over the final study month, relative to P0)
  is reported as a separate completeness metric - timing (how fast) and
  completeness (how much) are different H3 questions and must not be
  collapsed into one number.
- Rationale: 50% is the natural analogue of D-013's announced/dark threshold
  applied to a single prefix's own history rather than a population-wide
  probing baseline - consistent methodology across the paper rather than an
  independently chosen constant. The 25/80 bracket tests whether the H3
  restoration-speed ranking across ASN types is sensitive to exactly where
  the line is drawn.
- Alternatives considered: an absolute visibility floor (e.g. 0.5 flat,
  rejected - some prefixes never ran near 1.0 pre-shutdown, so a flat floor
  would misclassify low-baseline prefixes as unrestored even at full
  recovery); first-touch (any nonzero visibility) as the restoration event
  (rejected - too sensitive to single-peer flap noise, would read as
  "restored" on a single stray announcement).
- Implementation status: BUILT (2026-07-07). `src/analysis/joins.py::restoration_events`
  computes the per-block restoration timestamp (25/50/80% thresholds) and
  steady-state completeness on the primary 8h-grid series;
  `restoration_by_type` aggregates by ASN classification type.
  Found on real data: ~97% of blocks cross the 50% threshold at the very
  first primary-series snapshot after the P4 boundary - the 8h grid cannot
  resolve where inside that window the true crossing happened, so
  `median_delay_s` came out identical across every ASN type (a resolution
  floor, not evidence of simultaneous restoration). Added a companion pair,
  `fine_restoration_order` + `restoration_order_by_type`, using the
  `may2026_restoration` event window's raw BGP-update timestamps instead of
  the 8h grid - first reannouncement per block after the P4 boundary. This
  resolved real by-type differences (median 1.5min for mobile/government to
  47min for unclassified ASNs). Along the way, found AS39501 (Parvaresh
  Dadeha) was classified `hosting` but behaved like the general population
  (slow, uniform) rather than the fast/always-reachable CDN cohort;
  bgp.tools independently confirms it as an eyeball/access-ISP network
  (#45 Iran eyeballs), not hosting - FF approved reclassifying it to `isp`
  in `data/population/ir_asn_classification.csv` (2026-07-07), which moved
  hosting's median from 78min (an artifact of this one ASN, 47% of the
  category's blocks) to 14.9min, in line with the other CDN/hosting orgs.
- Implemented in: `src/analysis/joins.py` (`restoration_events`,
  `restoration_by_type`, `fine_restoration_order`, `restoration_order_by_type`);
  tests in `tests/test_restoration.py`, `tests/test_joins.py`.
- Affects: H3 (centerpiece restoration figure).

## D-024 — Resolution of D-010: onset/event duration metric (H4)
- Status: DECIDED (2026-07-06, FF signed)
- Question: "Time from first to last withdrawal" is sensitive to stragglers;
  decide between full range and an interpercentile range, applied
  identically to nov2019, jun2025, feb2026_onset, and may2026_restoration.
- Decision: primary metric is the 5th-95th percentile interpercentile range
  of per-prefix first-withdrawal times (i.e. t_p95 - t_p5, not t_max - t_min).
  Full range (t_last - t_first) is reported alongside as a secondary/context
  metric, never used alone to compare windows.
- Rationale: interpercentile range is robust to the exact long-tail behavior
  that makes cross-window comparison misleading today - e.g. nov2019's full
  range (594,787s) is dominated by stragglers out past its own p99
  (484,468s), while its bulk (p50 17,340s) is actually the fastest of the
  three completed windows. A single straggler prefix can otherwise swing the
  full-range number by days; 5th-95th trims exactly that without hiding it
  (full range still reported for transparency).
- Alternatives considered: full range only (rejected - exactly the metric
  whose sensitivity to stragglers motivated this entry); p50/p90/p99 marginal
  percentiles only, no range (rejected - a set of quantile points isn't a
  single comparable "how long did onset take" number the way a range is;
  keep both forms since they answer different questions).
- Implementation status: BUILT (2026-07-06). `src/analysis/joins.py::event_speed`
  emits `duration_p5_p95_s` (= t_p95 - t_p5, the metric this entry decides on)
  alongside the pre-existing `duration_s` (full range) and `duration_p50_s`/
  `duration_p90_s`/`duration_p99_s` (elapsed time from t_first to each
  percentile - a different question, "time to reach the Nth percentile from
  the start," kept as secondary/context stats, not a substitute for the range).
- Implemented in: `src/analysis/joins.py::event_speed`.
- Affects: H4 comparison table (all 4 windows once jun2025 lands).

## D-025 — Resolution of D-001: phase boundary dates, derived from data
- Status: DECIDED (2026-07-06, FF signed)
- Question: exact UTC timestamps for the P0/P1, P1/P2, P3/P4 boundaries
  (D-001), derived from the country-level IODA + aggregate BGP figure per
  D-001's own rationale, before any hypothesis-specific analysis is
  finalized on them.
- Method: reused D-013's already-decided probing_dark_ratio (0.2x own
  baseline) - deliberately not a new threshold invented for this purpose -
  applied to the country-level `ping-slash24` signal (native 600s
  resolution, zero coverage gaps per the 2026-07-06 IODA QC) against its
  fixed P0 baseline (`data/ioda/baseline/country_IR.parquet`, same window as
  D-013). Ran a **blind full-study-period scan** for sustained (>=2 day)
  excursions below threshold, rather than only searching near the
  press-reported prior dates, to avoid finding what the priors expected to
  find. The scan surfaced exactly three excursions:
  1. 2025-06-19 -> 2025-06-21 (2 days) - matches the already-known June 2025
     war-blackout reference event inside P0 (sanity-checks the method
     against known history).
  2. **2026-01-08T16:50Z -> 2026-01-27T00:10Z (18 days)** - a previously
     uncharacterized event. NOT in the current phase model at all (currently
     Dec 20 2025 - Feb 27 2026 is one undifferentiated "throttling" phase).
  3. 2026-03-01 -> 2026-05-26 (86 days) - the known hard-blackout plateau.
- Motivating finding (full detail): the current P1 window (2025-12-20 ->
  2026-02-27, "throttling / selective blocking") shows NO detectable
  transition in either the country-level probing signal or the per-ASN
  `announced_but_dark` share anywhere near 2025-12-20 - both stay flat at
  the P0 noise floor (country ratio ~0.99-1.00; per-ASN dark share
  ~0.04-0.16%) through all of December. Instead there is a sharp, isolated,
  control-checked event entirely inside the nominal P1 window:
  - Onset: ratio falls from ~0.92 to ~0.04 in ~30-50 minutes starting
    2026-01-08T16:30Z (country signal); per-ASN dark share simultaneously
    jumps from ~0.1% to ~14.5%. 123 distinct ASNs register dark at some
    point across the 18 days, including TCI (AS58224), TIC (AS49666),
    MCI/Hamrah-e-Aval (AS197207), Irancell (AS44244), and Rightel
    (AS57218) - i.e. essentially every major carrier, not a narrow slice.
  - Withdrawn share does NOT move during this window (stays ~19-23%
    throughout) - this is a filtering-type event like the main blackout,
    not a withdrawal event.
  - Offset: sharp initial recovery 2026-01-26T23:50Z -> 2026-01-27T01:00Z
    (ratio 0.03 -> ~0.37), then a SLOWER multi-day tail back to full
    baseline by ~Jan 29-31 - recovery is not as sharp as onset.
  - **D-008 gate: 0% dark share in all 30 control ASNs (TR/AE/PK) across
    the entire Jan 8-31 window** - not a measurement artifact.
  - Bonus refinement en route: native-resolution re-check of the already-
    known Feb 28 onset finds the country probing signal crossing dark at
    **2026-02-28T07:50Z**, about 1h12m BEFORE the documented 09:02 UTC BGP
    withdrawal wave. The [[killswitch-h1-finding]] memory had flagged
    "dark-before-withdrawal sequencing" as a LOW-confidence lead because
    8h RIB-snapshot bins were too coarse to time it; native 600s IODA
    resolution now times it directly. Tier: observed (the sequencing
    itself); any claim about *why* stays at consistent-with-reporting at
    most (D-011).
- Proposed decision (values, pending sign-off):
  - P0: 2025-05-01T00:00:00Z -> **2026-01-08T16:50:00Z** (moved from
    2025-12-20; no data-supported reason to end P0 at the press-reported
    date - the country signal is indistinguishable from baseline for the
    entire Dec 20 - Jan 8 span. Explicitly note in methods: no measurable
    transition was found at the press-reported "late Dec 2025" date in any
    signal checked; if throttling began then, it did not register as a
    change in active-probing response counts or per-ASN reachability at
    the aggregate levels available to this study.)
  - P1: **2026-01-08T16:50:00Z -> 2026-02-28T07:50:00Z** (moved from
    2025-12-20 -> 2026-02-27; now spans exactly the January dark event
    (Jan 8-27) plus the ~32-day return-to-baseline interim before the hard
    onset (Jan 27 - Feb 28). This window is internally heterogeneous by
    construction - phase-level means over it will understate the January
    event and should be reported with the event called out separately, not
    folded into one P1 average.)
  - P2: **2026-02-28T07:50:00Z** -> 2026-03-01T00:00:00Z (start moved
    ~7h50m later than current 2026-02-28T00:00:00Z, to the actual measured
    onset instant. This also closes a pre-existing 24h gap in the phase
    model - P1 previously ended 2026-02-27T00:00:00Z and P2 previously
    started 2026-02-28T00:00:00Z, leaving Feb 27 uncovered by any phase;
    P1 now runs right up to the same instant P2 starts. End unchanged -
    D-001 didn't flag P2/P3 as needing verification and the blind scan's
    own sustained-dark run (2026-03-01 onward) corroborates it).
  - P3: 2026-03-01T00:00:00Z -> **2026-05-26T12:10:00Z** (end moved from
    2026-05-25, ~1.5 days later, to the measured recovery crossing).
  - P4: **2026-05-26T12:10:00Z** -> 2026-07-01T00:00:00Z (study_period end,
    unchanged).
- Robustness owed (pre-committed 2026-07-06, RUN 2026-07-07 - see result
  below): ±24h sensitivity sweep on the P1/P2 boundary specifically, per
  D-001's original robustness note, since H4's onset-duration metric
  (D-024) is what's most sensitive to it; rerun the full-period P0-P4
  breakdown (H1/H2/H3, 2026-07-06 run) under these boundaries and report
  whether the qualitative filtering-dominant shape survives (expected: yes,
  since the shape was already driven by P2/P3 vs P0, and P0/P2/P3 barely
  move; P1's own numbers will change materially since its span and
  composition both change).
- **Robustness result (2026-07-07):** the flat ±24h figure was inherited
  from D-001's pre-D-025 robustness note (written when boundaries were
  coarse press-reported dates) and was never revalidated against P2's own
  width once D-025 narrowed it to 16.2h - a ±24h shift exceeds that width
  entirely. Run as specified (`src/analysis/phase_breakdown.py::boundary_sensitivity_sweep`,
  `outputs/p1_p2_boundary_sensitivity.csv`): at -24h, P2's dark_share drops
  from 13.79% to 5.59% (more than halved); at +24h, the shifted boundary
  lands past P2's own end (2026-03-01T00:00) and the phase is empty
  (undefined, not zero). Neither result means the finding is fragile - it
  means the primary series' 8h snapshot grid gives P2 only 2 sample
  instants (2026-02-28 08:00 and 16:00, the boundary sitting 10 minutes
  before the first), so ANY shift either changes nothing (doesn't cross a
  snapshot) or swaps in a different regime's data wholesale (P1's flat
  pre-transition baseline, >7h50m back; empty space, >16.2h forward) - a
  step function, not a smooth quantity a continuous +/-Xh sweep can
  meaningfully probe. The informative check is the raw snapshot trajectory
  (`snapshot_trajectory`, `outputs/p1_p2_transition_snapshot_trajectory.csv`):
  2026-02-28 00:00 dark_share 0.12% -> 08:00 **14.29%** -> 16:00 13.30% ->
  2026-03-01 00:00 (first P3 snapshot) 13.42%. This shows a genuine
  single-step jump between 00:00 and 08:00 (consistent with the
  independently-measured ~40min transition landing inside that 8h gap),
  and - the actually reassuring part - the post-jump level is immediately
  stable and matches P3's own plateau from its very first snapshot: P2's
  reported 13.79% (mean of its 2 snapshots) is not an arbitrary or fragile
  average, it's representative of a plateau that was already flat by the
  time P2 starts. The qualitative filtering-dominant shape survives; the
  original expectation that "P0/P2/P3 barely move" under this sweep did
  NOT survive as stated (P2 moves a great deal under a naive ±24h test)
  and is corrected here to the snapshot-level characterization instead.
- Alternatives considered: keep press-reported priors and only footnote the
  January event (rejected - directly contradicts D-001's own rationale that
  boundaries must be derived, not assumed, and would leave a materially
  misleading P1 average in the paper); fold the January event into P0
  instead of giving P1 to it (rejected - an 18-day, ~96%-country-signal-
  collapse, control-validated event is not "baseline" by any reasonable
  reading, regardless of what phase number it gets).
- Implemented (2026-07-06): `config/phases.yaml` P0-P4 boundaries updated to
  the values above (also closes a pre-existing 24h phase-model gap between
  the old P1 end and P2 start, both nominally Feb 27/28); `event_windows`
  gained `jan2026_event` (2026-01-07 -> 2026-01-28, a day of margin each
  side) for a future full BGP update-stream pull (minute-resolution, like
  `feb2026_onset`) - queued behind `jun2025` intentionally, per the
  2026-07-06 OOM lesson against running concurrent heavy collection jobs on
  the same EC2 host; the event window itself has NOT been pulled yet.
  Full-period H1-H4 phase breakdown rerun under the new boundaries; see
  [[killswitch-h1-finding]] for results.
- Affects: everything downstream (D-001's own scope); directly changes the
  P0-P4 numbers reported 2026-07-06 (this session); H4 (adds a 4th real
  event, arguably more analytically interesting than jun2025 for cross-
  event comparison once it has its own event window).

## D-026 — Resolution of D-013 steps 4/5: final visibility/dark-ratio thresholds
- Status: DECIDED (2026-07-07, FF signed)
- Question: D-013 left `visibility_announced_min` and `probing_dark_ratio`
  as provisional pipeline defaults (0.5, 0.2), deferring the final values
  to two sub-steps that were never executed: (4) place
  `visibility_announced_min` in the empty valley of the P0, per-AS
  visibility distribution, with a literature-precedent check taking
  priority if a verifiable one exists; (5) calibrate `probing_dark_ratio`
  on the D-008 control population in quiet periods, choosing the largest
  ratio whose false-dark rate is < 1%. Every H1 number reported to date
  rests on these unfinalized values (`config/phases.yaml` carried the
  comment "No H1 number computed with these is reportable").
- Method: `src/analysis/threshold_calibration.py`
  (`p0_visibility_histogram`, `find_valley`,
  `dark_ratio_false_positive_sweep`, `largest_ratio_under`), plus a
  literature search for step 4's precedent check.
  1. Visibility: computed the P0 per-AS visibility histogram (200 bins,
     `_per_as_visibility` collapsed to P0's window) - found a clean empty
     valley at [0.465, 0.480], midpoint 0.4725. Literature check: IODA's
     own BGP methodology defines visibility as "seen by at least 50% of
     the peers at the route collectors" (CAIDA/APNIC, verified via
     WebFetch/WebSearch, not memory) - a directly comparable precedent
     that lands just outside the empirical valley's upper edge. Per D-013
     step 4's own priority rule, the verified precedent (0.5) is used;
     confirmed on real data that 0.4725 and 0.5 produce byte-identical
     `bgp_vs_ioda` output (no AS-timestamp pair falls between them), so
     this is a genuine no-op choice between the two, not a compromise.
  2. Dark ratio: first pass calibrated the false-dark-rate sweep on P0
     only, found 0.8 (crossover at 0.85, 1.79% false-dark). Checked against
     the existing D-008 bin-level artifact gate over the FULL study
     period and it failed badly - 176/1278 bins artifact-flagged, some
     control ASNs hitting 50% "dark" share, concentrated in a handful of
     low-baseline/noisy control ASNs (AE 41268/8966/216071, PK
     59257/59605/38710) whose ping-slash24 signal is inherently high-
     variance relative to a small baseline median. The P0-only sweep was
     an overfit to one slice of the control data - "quiet periods" for a
     control population with zero documented caveats
     (`config/controls.yaml` caveats: []) means the full study period, not
     just P0, since that's the actual scope the ratio is applied over.
     Recalibrated the sweep on the full study period (1278 bins x 30
     controls, 38,340 pairs): false-dark rate crosses 1% at ratio=0.45
     (1.00%); 0.40 is the largest ratio staying strictly under 1%
     (0.978%). Re-checked the D-008 bin-level gate at 0.40: 5/1278 bins
     flagged (vs 0/1278 today), mean control dark_share 0.98% - materially
     better than the rejected 0.8 candidate, a small residual noted rather
     than hidden.
- Decision: `visibility_announced_min = 0.5` (unchanged from the
  provisional value, now backed by literature precedent + empirical valley
  rather than being a placeholder); `probing_dark_ratio = 0.4` (up from
  the provisional 0.2).
- Rationale: same structure as D-013's own procedure - precedent takes
  priority for the threshold that has one and is verifiable; the ratio is
  calibrated on non-analysis (control) data using the actual scope it will
  be applied over, not a convenient subset. The P0-only sweep's failure is
  reported as part of the record, not smoothed over, per this project's
  own culture of surfacing test-design mistakes (D-020, D-025).
- H1 impact (checked before sign-off, `python -m src.analysis.joins.bgp_vs_ioda`
  + `phase_breakdown.dark_and_withdrawn_share` rerun under both value
  sets): dark_share moves modestly and in the same direction at every
  phase - P0 0.31%->0.39%, P1 5.37%->5.75%, P2 13.79%->14.59%, P3
  14.28%->15.02%, P4 2.01%->3.31%. P0 stays near-zero (baseline sanity
  check passes); the filtering-dominant, P2/P3-peak qualitative shape is
  unchanged. P4's relative jump (2.01%->3.31%, the largest proportional
  move of any phase) is consistent with - and sharpens - the "partial,
  still-degraded" reading of the restoration phase.
- Alternatives considered / robustness checks owed: the D-013 step-6
  robustness grid (threshold +/-0.25, ratio {0.1, 0.3}) is still owed and
  pre-committed, now against these final values rather than the
  provisional ones; per-country breakdown of the 5 residual artifact-
  flagged bins at ratio=0.4, to confirm they don't cluster in a way that
  would warrant a `config/controls.yaml` caveat entry (deferred - not
  blocking, the residual is small and the gate is not used to exclude
  Iranian findings, only to flag them).
- Implemented in: `src/analysis/threshold_calibration.py`;
  `config/phases.yaml` (`analysis.probing_dark_ratio: 0.4`,
  `visibility_announced_min` unchanged at 0.5, comment updated to remove
  "provisional"/"not reportable" language); `src/analysis/controls.py`
  (`control_dark_rows` extracted from `control_dark_shares` for reuse).
- Affects: every H1 number in the paper; D-013 (closes its steps 4/5,
  formerly open); H3 secondarily (state-derivation logic is shared).
