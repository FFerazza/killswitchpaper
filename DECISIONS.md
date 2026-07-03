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
- Status: OPEN
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
- Status: OPEN
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
- Status: OPEN
- Question: The event marking a prefix "restored": first timestamp after the P4 boundary where
  visibility re-crosses X% of that prefix's own P0 baseline.
- Decision: —
- Candidate: X = 50 as primary; 25 and 80 as pre-committed robustness runs. Additionally
  report steady-state visibility (mean over final study month, relative to P0) as the
  completeness metric, separate from timing.
- Implemented in: `src/analysis/` survival prep
- Affects: H3 (centerpiece figure).

## D-007 — AS classification scheme and validation
- Status: OPEN
- Question: The type taxonomy (state_telecom, mobile, isp, government, financial, hosting,
  education, other), coding rules for ambiguous cases (e.g. state-owned ISPs serving
  consumers), and the inter-coder validation protocol (sample size, agreement statistic).
- Decision: —
- Rule already in force: `data/population/ir_asn_classification.csv` is hand-curated,
  versioned, never programmatically overwritten.
- Implemented in: the CSV + a coding-rules appendix
- Affects: H3 entirely.

## D-008 — Control population
- Status: OPEN
- Question: The set of non-IR ASes (candidate: 20–30 from TR, AE, PK) used to distinguish
  measurement-infrastructure artifacts from Iranian events. Selection rule must be stated
  (e.g. matched roughly on size and region) and fixed before event analysis.
- Decision: —
- Implemented in: `config/phases.yaml` or `config/controls.yaml`
- Affects: validity of every anomaly claim.

## D-009 — Flap definition (H4 "cleanliness")
- Status: OPEN
- Question: What counts as a flap during an onset window: a withdrawal followed by
  re-announcement of the same prefix within T minutes, from the same origin. Value of T.
- Decision: —
- Implemented in: `src/analysis/` event metrics
- Affects: H4 comparison table.

## D-010 — Onset duration metric (H4)
- Status: OPEN
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
