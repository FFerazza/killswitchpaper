CLAUDE.md — Iran 2025–26 shutdown reconstruction study

Measurement study reconstructing Iran's 2025–26 internet shutdown from BGP and outage
data. Read READE.md for pipeline objectives and structure, DECISIONS.md for the
analytical decision log. Both are binding.

Non-negotiable rules

Analytical parameters

Before using ANY threshold, cutoff, exclusion rule, accounting rule, or definition in
analysis code, check DECISIONS.md. If no DECIDED entry covers it: propose a new entry
(status PROPOSED, with rationale and robustness checks) and STOP for human sign-off.
Never pick a value silently. Never justify a value by which hypothesis it favors.
DECISIONS.md is append-only: never edit or delete a DECIDED entry; supersede it.

Protected files


data/population/ir_asn_classification.csv is hand-curated. NEVER regenerate or
overwrite it. New ASNs are merged in with type left blank for manual coding.
DECISIONS.md: append-only, per above.


Citations (paper/)

NEVER generate a BibTeX entry, DOI, title, author list, or venue from memory.
Only cite keys that already exist in paper/references.bib. If a claim needs a source
that isn't in the .bib, insert \todo{CITE: <description>} and list it at the end of
your turn for the human to resolve. This rule has no exceptions.

Attribution tiers (paper/)

Every empirical sentence in the paper carries exactly one tier:


observed — directly present in our measurement data.
strongly implied — measurement pattern + tight temporal ordering + at least one
independent corroborating source; alternatives implausible.
consistent with reporting — plausible interpretation resting on external reports.
Causal claims about actors (government orders, ministry decisions) can never exceed
tier 3 on measurement data alone. When drafting, flag any sentence whose tier is
ambiguous rather than guessing.


Numbers in prose

No empirical number is ever typed into .tex by hand. Analysis code emits
paper/results.tex as \newcommand macros; prose references macros only. If a needed
macro doesn't exist, add it to the emitting script.

Analysis conventions


All analysis through committed scripts in src/analysis/ and src/figures/;
no throwaway exploration whose logic isn't preserved.
Every event/anomaly finding must be checked against the control population (D-008)
before being treated as an Iranian event. A pattern that also appears in controls is
a measurement artifact.
Actively look for disconfirming evidence for H1–H4; report it, don't smooth it over.
Timestamps: UTC everywhere, unix seconds in storage, ISO 8601 in logs and figures.
Config over constants: dates, ASN lists, thresholds live in config/, never inline.
Stages must stay idempotent and resumable; full-period BGP runs are expensive —
never launch one without confirming the test-week run validates first.


Writing conventions (paper/)


Methods prose is generated from DECISIONS.md entries: each DECIDED entry maps to a
methods paragraph stating the choice, rationale, and robustness checks.
Build with latexmk -pdf from paper/; fix compile errors before returning.


Session hygiene


One concern per session: analysis sessions and writing sessions are separate.
At the end of any session that made analytical choices, confirm DECISIONS.md
reflects them before finishing.
