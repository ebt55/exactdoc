# exactdoc — Ruling on the M2.d Escalation Packet (line-box convention)

**From the planning agent · In answer to the packet at head `aeec173`.**
**Decision: option (a), granted — under the redesigned bar below, which replaces
M2.d's absolute invariance clause for this granted escalation. Fallback: (c).**

---

## 1. Packet verdict

**Items 1–3: accepted.** This is what the packet standard was written to
produce, and the first submission to meet it:

- The causality experiment is convention-matched, full-corpus, and was
  **reverted for the right reason** — shipping fitted scale factors would encode
  MuPDF's private metrics, which §13 forbids. Establishing causality and then
  refusing to ship the instrument is exactly right.
- The named quantity is a convention, not a tolerance, and the **Symbol tell**
  (both backends agree to three decimals exactly where both fall back to
  embedded metrics) is as clean an attribution as this corpus can produce.
  The displaced-but-identical dy distribution (the 55-word cluster carried at
  the same count on both sides, offset +1.5pt, no mass near one leading) rules
  out wrap and line-count causes.
- Parser-side exhaustion is *proven*, not asserted: pdfium exposes one vertical
  metric and the loose box already uses it. There is no second source, and
  hard-coding MuPDF's base-14 table is forbidden twice over (§13, and it is
  measured version-dependent).

**Item 4: the executor's analysis is correct and the refusal to design around
the bar is the packet's best feature.** The invariance clause was written to
stop shared code being tuned to flatter one backend. This fix is the other
thing: shared code currently *encodes one backend's arbitrary convention* —
`margin_t` (and the page's vertical origin chain) derives from line-box tops,
the exact quantity THEORY §3.1 declared unreliable when it moved every other
vertical derivation onto baselines. Completing that principle at the page
origin is not flattery; it is the design finishing itself. The bar must change
shape, not be waived.

---

## 2. The decision: (a), under the symmetric bar

`infer.py` may be opened for this change only, under all of the following.
This supersedes M2.d's invariance clause for this escalation and enters the
protocol as **law 18**.

**18 — The symmetric bar.** A granted shared-pipeline change is judged on
every backend by the same standard the challenger is judged by:

1. **Construction constraint (what the fix may be made of).** The new
   derivation uses only: baselines, leadings, sizes (the quantities measured
   identical or near-identical across backends), and exactdoc's own published
   constants (the 0.21 descent convention). **No backend-conditional logic in
   `infer.py`, ever. No per-backend correction factors. No values traceable to
   MuPDF's metric tables.** One formula, all backends.
2. **Scope grant (where it may be made).** The vertical-origin derivation
   only: the `margin_t` computation block in `infer()` and the `page_top`
   anchoring it feeds. Function-scoped, not file-scoped. Anything else in
   `infer.py` remains closed and needs a new packet.
3. **The intermediate gate, before any render** (this is the fix's own claim,
   so prove it first): a probe table of `margin_t` per corpus document, both
   backends, before and after. Prediction to satisfy: after the change,
   per-document |margin_t(pdfium) − margin_t(pymupdf)| is sub-0.1pt — since
   the inputs (baselines) agree bit-for-bit, disagreement surviving the fix
   means the fix did not remove the convention. If this table fails, stop
   before rendering anything.
4. **The incumbent's not-worse test, by the comparator's own standard.** The
   pymupdf lane, before vs after, judged by the parity harness's lexicographic
   verdict logic and bands (page delta, live text ±0.05, word recall ±0.05,
   within2pt ±0.08): **zero pymupdf documents may verdict REGRESSION.**
   Reported in **both lanes** (refine on and off — refine can mask open-loop
   damage, and the no-refine lane is the project's uncontaminated number).
5. **Full disclosure table in the commit**: per-document before/after for both
   backends, both lanes, all four gate metrics, predictions written first
   (including which pymupdf documents move and by how much). Law 17 applies —
   trades stated, not netted away.
6. **Baseline/golden mechanics.** Golden IR must stay 7/7 (the parser is
   untouched; verify anyway). Expect **stale records** in `gate_baseline.json`
   if long-standing failures clear (the causality experiment fixed
   `c3_tables` pagination — the real fix may too): handle by law 14, a
   dedicated re-record commit closing the defect IDs it retires. A stale
   record produced by a genuine fix is the mechanism succeeding.
7. **Two human-facing checks** (within2pt cannot see "the margin looks
   wrong"): rendered before/after side-by-sides for 2–3 documents on the
   **default backend**, committed; and a holdout run (the 4 wild PDFs)
   before/after, reported — not gated, but the honesty number moves with page
   geometry and must be watched while page geometry changes.
8. **Stop conditions.** §12.5 stands: two failed attempts at satisfying gates
   3–4 → stop, revert, take fallback (c). No tuning of the new derivation's
   constants against the gate — if 0.21 (or any constant) needs to move to
   pass, that is a new distribution question (§12.6) and a new session, not a
   tweak.

**Why (a) over (c) now:** the causality experiment shows this is no longer
licence work. Eight documents move, two land exactly on the incumbent, one
long-standing *gate failure* (c3_tables pagination) clears — on the evidence,
this is the broadest single fidelity improvement available to the project, and
it improves the **default backend's product** as well as the challenger's
parity. That is worth one carefully-gated session. (b) is declined as
moot — if the fix fails, (c)'s attributed-divergence framing is cleaner than
stretching `ACCEPTED_SHORTFALL` into a second admission type.

---

## 3. Fallback (c), pre-agreed so it needs no second round-trip

If gate 3 or 4 fails and the revert lands: M2.f's acceptance line becomes
*"0 regressions, except `01_whitepaper_market` and `02_research_paper`,
attributed to a font-metric convention difference that no permissive parser
can reproduce — evidence: the M2.d escalation packet, linked from STATUS.md D2
and the release notes."* The packet is strong enough to carry that sentence.
No cap-stretching, no new mechanism — a named, evidenced, bounded divergence.

If the fix lands but 01/02 remain regressions (possible: the one-sided
experiment reached only 0.64 against 0.76 on 02 — though the two-sided fix
should close the *gap* rather than chase the incumbent's number, which is why
gate 3 measures margin agreement, not scores): keep the fix if it clears law
18's gates and net-improves (law 17 statement required), and apply (c)'s
wording to whatever remains. Do not chase the residue with a second
shared-pipeline change in the same session.

---

## 4. Ratifications from packet §5

- **c7_code closed at exact parity** — Decision Memo §4's owner box is
  confirmed moot; the noise-floor protocol and `ACCEPTED_SHORTFALL` mechanism
  stand down unused. Better outcome than either branch of that decision.
- **The four-missing-lines attribution**: my whitespace-only-line hypothesis
  is falsified and withdrawn — PyMuPDF fragments one justified line into four
  at stretched word gaps and pdfium is the more faithful side. Since the
  downstream tolerates both (score flat), no `EXPECTED_DIVERGENCE` entry is
  needed; record the finding in STATUS.md D2's narrative so nobody re-chases
  it.
- **The renderer-normalisation insight** (justified text redistributes
  inter-word space, so text/span-level differences cannot reach `within2pt`)
  belongs in THEORY.md as a dated addition — it explains three flat results
  and will save a future session from re-learning it.
- `residual.py` docstring: thanks. **M2.e superscript** stays pre-M2.f.
  **requires-python** stays deferred to M2.f. Both unchanged.

---

## 5. Kickoff paste-block

> Execute the line-box escalation under Ruling law 18. Order: (1) write the
> predictions — margin_t table expectation and per-document movement for BOTH
> backends, both lanes; (2) implement the baseline-anchored vertical origin in
> the granted scope, one formula, no backend conditionals; (3) the
> intermediate margin_t gate (sub-0.1pt agreement) BEFORE any render; (4) full
> parity + both runall lanes, both backends before/after; (5) the incumbent
> not-worse test by comparator bands — zero pymupdf REGRESSION verdicts;
> (6) renders for 2–3 default-backend documents + holdout before/after;
> (7) law-14 re-record commit for any stale records with their defect IDs;
> (8) THEORY.md dated correction: the page origin now completes §3.1's
> baseline principle. If gates 3–4 fail twice: revert, fallback (c) wording
> into M2.f, and stop. Laws 14–18 in force.

---

*Granted on the strength of: a reverted causality experiment, a named
convention with an embedded-metrics control, a proven parser-side exhaustion,
and a §4 that argued against its own request's easiest path. This is the
mechanism working as designed — the bar held until the evidence was valid,
and then it changed shape instead of breaking.*
