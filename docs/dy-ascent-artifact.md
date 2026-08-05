# `dy_p50`, glyph tops, and the base-14 ascent artifact

**Decision record for task #22.** Small `dy_p50` differences between the two
parser backends are a measurement convention, not a placement error. This
records why, what was decided, and what was deliberately *not* done.

---

## The artifact

`dy_p50` is the median vertical difference between a word in the source PDF and
the same word in the rendered output. It is computed on **glyph tops**.

A glyph top is not a measured quantity — it is derived, as `baseline − ascent`,
and the ascent comes from the font. For the base-14 fonts, the two backends read
different ascents for the same font:

| backend | Helvetica ascent, as reported |
|---|---|
| PyMuPDF | the declared value, 1.070–1.075 em |
| PDFium | a substituted generic, ~0.905 em |

The gap is about 0.17 em, so the apparent vertical offset scales with type size:

```
0.17 × 10.5pt  ≈  1.8pt
```

**The baselines are identical.** Both backends put the text in the same place;
they disagree only about where the top of the letter is said to be. Every
downstream consumer — the writer, the renderer, the reader — uses the baseline.
Nothing a reader can see moves.

This is why the affected documents cluster so tightly: the artifact appears on
base-14 documents and nowhere else, because a document that embeds its fonts
gives both parsers the same real metrics to read.

## Why it looked like a regression

`dy_p50`'s margin in `parity_policy.json` is proportional — 10% of the reference
value — with a 0.5pt absolute floor. That is sensible across a corpus where the
metric runs from 0.04pt to over 100pt. Near zero, though, the proportional term
vanishes and the 0.5pt floor is the entire rule, so a document moving from
0.04pt to 1.29pt is graded a regression on a difference smaller than a fraction
of one line's leading.

At the shipping settings, five gated base-14 documents landed in exactly that
band: `01_whitepaper_market`, `02_research_paper`, `03_tech_report_code`,
`05_memo`, `f1_fpdf_brief`. Every one of them was reported as a `dy_p50`
regression, and every one of them was reporting the ascent convention rather
than a placement change.

## The decision: the metric definition stays glyph-tops

The obvious fix — redefine `dy_p50` on baselines — was considered and
**rejected**.

Changing the definition of a metric is a baseline event, and this metric is
recorded in three independent bodies of committed evidence: the gate baseline
(`testkit/gate_baseline.json`), this parity policy's floors, and every live
Google pass record. Redefining it would invalidate all three *simultaneously*,
forcing a re-record of each, in order to correct a reporting convention that
moves nothing a reader sees. The cure would cost more evidence than the disease
costs accuracy.

So the artifact is handled where it actually bites — in the comparison — by a
bounded absolute-magnitude exemption, and by this document.

## The exemption, and the condition that keeps it honest

`parity_policy.json` carries `dy_absolute_exemption`: a `dy_p50` delta is not a
regression when **both arms are already under 2.0pt**, *provided* `within2pt`
did not move adversely on the same document.

The condition is the load-bearing half. `within2pt` counts the words actually
landing within 2pt of source, so it states directly what `dy_p50` only proxies —
and the two demonstrably move in opposite directions. `x02_lo_report_toc` moves
`dy_p50` 8.3 → 13.1 while `within2pt` **improves** 0.0608 → 0.1877. A magnitude
rule with no condition would have excused any document small enough, including
ones whose placement genuinely degraded.

It does exactly that here. At the shipping settings, five documents sit inside
the 2.0pt ceiling but the rule clears only **three**:

| document | dy_p50 | within2pt | cleared? |
|---|---|---|---|
| `01_whitepaper_market` | 0.5 → 1.38 | 0.7194 → 0.6611 | yes |
| `05_memo` | 0.59 → 1.39 | 0.6386 → 0.6386 | yes |
| `f1_fpdf_brief` | 0.0 → 1.2 | 0.621 → 0.6048 | yes |
| `02_research_paper` | 0.04 → 1.29 | 0.7614 → **0.5685** | **no** |
| `03_tech_report_code` | 0.54 → 1.49 | 0.4602 → **0.2803** | **no** |

`02` and `03` lose about 0.18 of `within2pt`, far outside its 0.08 margin. Their
placement really did degrade, so the exemption declines to touch them and both
keep a `MAJOR` verdict on `within2pt` — which they would have kept regardless,
since `within2pt` is independently worse. The condition therefore costs nothing
in outcome and buys an accurate statement of what the rule does.

At the candidate profile the rule clears exactly one document,
`x13_rl_report_running` (0.85 → 1.36), the only base-14 document in its class
there.

## Why 2.0pt, and why it must not be raised

The ceiling sits in empty space rather than just above a failure. At the
shipping settings the exempted values top out at 1.49pt and the next `dy_p50`
magnitude anywhere in the corpus is `c3_tables` at 2.75pt — already graded
`same`, so it is not competing.

Raising it would blind the policy fast. The next divergences up need roughly:

| document | ceiling that would absorb it |
|---|---|
| `x02_lo_report_toc` | ~13pt |
| `x10_chrome_tables_plain` | ~17pt |
| `x07_chrome_memo_running` | ~21pt |
| `y17_rfc9110` | ~68pt |

Those four are genuine structural divergences — they are the pdfium
line-segmentation convergence campaign — and a ceiling large enough to absorb
any of them would stop the policy seeing all of them. **2.0pt is a bound on a
known measurement convention, not a tolerance for placement error.**

## Scope

The exemption is keyed by full profile ID and never borrowed across profiles.
`dy_p50` at the shipping settings and at the candidate profile are different
distributions measured through different renderers, so a ceiling calibrated on
one says nothing about the other — the same reasoning that makes the policy
refuse to adjudicate across a profile boundary at all. `adjudicate` selects only
the section matching the run's profile; a section recorded for a profile the
policy does not govern is inert by construction.
