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
