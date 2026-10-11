# Checkpoint — 2026-10-11 (round 4)

Round 4 ran from the round-3 checkpoint ([checkpoint-2026-10-06.md](checkpoint-2026-10-06.md))
to the final measurement of 2026-10-11. The coordinator planned; Opus 5.5 agents
implemented in isolated worktrees; owner decisions and owner-delegated
decisions (Fable 5.1, and for the re-record a Fable 5.1 + Opus 5.5 dual review)
settled every bar question on the way.

**State: READY on `9adf283`** — `beta_readiness --release 0.3.0b1`: **10 pass, 0
fail, 0 unmeasured, 3 reported**
([beta-readiness-2026-10-11.json](evidence/beta-readiness-2026-10-11.json)).
Nothing is published. The version is unchanged (0.2.0a1), there is no tag,
and `main` is untouched. Publishing to PyPI and tagging 0.3.0b1 are the owner's
call. Every merge is on `claude/exactdoc-pdf-docx-tool-d4bf20`, pushed.

The final measurement was one clean run of `scripts/dev/final_set.sh` on
integration `910e6aa`, with no `--allow-*` flag. Every input carries that one
commit and harness reading `wp42`
([final-set-2026-10-11.json](evidence/final-set-2026-10-11.json), each input
by path and SHA-256). The run had:
- a strict gate, bound to its baseline (1954 tests OK; both lanes PASS, 16/16
  pages);
- LibreOffice product and raw sweeps of all 90;
- the Word lane, product and raw (90/90 opened, no repair prompt);
- the live Google Docs sweep of all 95, with the drift sentinel "ok" under
  wp42;
- serial timing on a quiet machine (y06 147.5 s against its 189 s limit).

`readme1` then refreshed the README from that run (criterion 12), which is
`9adf283`.

## Decisions, and who made them

| Date | Decision | Decider |
|---|---|---|
| 2026-10-10 | **Carlito switch.** The canonical image is the Carlito/Caladea layer (`exactdoc-gate:boot` = bab1cfc0d2cd, fingerprint 9cb0bc17). The old snapshot is kept as `boot-pre-carlito`. WP32 | owner |
| 2026-10-10 | **Amendment 3.** Placement (within-2pt, dy_p50/p90) is read at the text baseline, not the word box top, on source and render alike (`docs/beta-bar.md`). WP36 | owner |
| round 4 | **Accepted sweep for criterion 8.** `wp31-prod` (the checkpoint code + WP31 in the Carlito image), compared in the current reading. Final form: `accepted-wp31-prod.rescored5.sweep.json`, reading wp42, SHA-256 `fcb8ca97…` | owner |
| 2026-10-10 | **y37 decision #1.** A bounded dy_p50 exception for WP33's column split (27.38 → 30.96, wp29 reading). Reverted unused when WP33n removed the flag (`b496c0a`) | decided, then reverted |
| 2026-10-10 | **Amendment 4, "A+cap".** A dy_p50 rise beyond tolerance is not a criterion-8 regression when within-2pt rose by more than 0.05, within-5pt fell by at most 0.05, and the rise is at most max(3 pt, 30%). WP41b | owner-delegated: Fable 5.1 |
| 2026-10-10 | **Amendment 5.** A letter-spaced run reads as the word it spells (harness reading `wp42`). WP42 | owner |
| 2026-10-11 | **y37 decision #2, option A.** Land WP38b and re-instate a bounded waiver: y37 dy_p50 only, ceiling **33.0** pt (measured 32.00), release 0.3.0b1, reading wp42, against the accepted sweep by SHA-256. Void unless all four d′ bounds of `churn.py --check-y37` hold on the final renders; they hold on 910e6aa (recall 0.39, common dy ratio 0.991, within-2pt drop 0.0001, 24 pages < 27) | owner-delegated: Fable 5.1 |
| 2026-10-11 | **Gate-baseline re-record.** `testkit/gate_baseline.json` = SHA-256 `c00ae596…21db`, committed byte for byte (`88a2831`). One item beyond tolerance: raw 05_memo within-2pt 0.1205 → 0.0602 (amendment 3). The reviewers' corrections are recorded in [rerecord-2026-10-11.md](evidence/rerecord-2026-10-11.md) | owner-delegated dual review: Fable 5.1 approve, Opus 5.5 approve with conditions |

## What merged in round 4

| WP | Change | Measured effect |
|---|---|---|
| WP32 | Carlito image made canonical; round 4's "before" measured in both images | gate unchanged in the new image (0.7304 / 0.5466); 84/90 DOCX identical across round-3 code |
| WP33, 33n, 33r | columns welded at the gutter are cut there; y64's table titles are written (heads must clear the body). The spacing-cursor hold was narrowed to tables (33n), then to rules only (`b32abf6`) | LO raw y64 44 → 39 (wr 0.34 → 0.97); y06 163 → 151, y13 58 → 50; criterion 5 Word and Docs 16 → 17 |
| WP34 | page-fit planner on for LibreOffice and Word (gentle-plan cap, hanging row is its body, planned once under the loop) | raw y18 156 → 144 (wr 0.40 → 0.98), page-exact 60 → 62; Word y18 154 → 144 |
| WP35 | gdocs: EUR-Lex run-in numbered articles stay typed; NIST shaded notice boxes written whole | live Docs y18 146 → 144 (wr 0.70 → 0.99) |
| WP35b | a typewriter table's columns are its typed spaces | y03 Docs 47 → 46 (wr 0.854 → 0.948) |
| WP35c | gdocs: tables hang their border like Word; tracked paragraphs narrowed for Docs | c3 and the short tables' text on their columns in Docs; x07 criterion 7 |
| WP35d | a form label opens its field; paragraphs a little apart stay apart; ladder hang labels | y65 dy_p50 10.1 → 1.5, y44 29.6 → 1.9 (raw); y02 raw 115 → 114 (wr 0.75 → 0.97) |
| WP35e | a paragraph step at the bar must recur, or clear 0.3 em alone | y20 Docs back to 5.2 (wp35d had 18.1); only y08, y17, y20 change |
| WP36 | amendment 3 (baseline placement) | gate renders re-read 0.7304 → 0.8156 product, 0.5466 → 0.6168 raw |
| WP38 | a refined write keeps the source's page seams between column pages | y21 48 → 49 of 48 (wr 0.52 → 0.88) LO; Word y21 50 → 49 (criterion 5 both lanes) |
| WP38b | the loop stops on a stalled spill; the first render judges where the seam plan gave up; unchanged candidates not re-rendered (`9bfb862`) | y21 serial 76.7 → 55.3 s; y61 dy_p50 43.9 → 37.5; total convert time 2821 → 2418 s |
| WP39 | the refine loop corrects at the baseline | product mean within-2pt 0.396 → 0.420, no page count moved |
| WP39b | a pushed page is planned as before the push, the push added back (`42eebbd`) | WP39 with WP34 had dropped y18's product within-2pt 0.145 → 0.009 (and y02 dy_p50 1.73 → 2.42); 39b removed that interaction |
| WP40 | y12's three seam-breaking pages read right (cover type jump, set-apart lines, framed photo, checklist gutters, leaders, knockouts) | y12 LO 61 → 59 of 59, wr 0.38 → 0.96 |
| WP41, 41b, 41c | criterion-8 waivers; amendment 4; sweeps record their reading; `churn.py` | scorecard machinery, no conversion change |
| WP42 | amendment 5 (tracked runs read as words) | x17/x18 wr 0.953 → 0.985 (LO/Word), 0.889 → 0.979 (Docs) |
| WP43 | baseline binding, provenance, the Docs drift sentinel, the Word lock, crash attribution | criterion 11 needs a bound gate |
| WP44 | `final_set.sh`: the final measurement set in one resumable command | this checkpoint's run |
| WP45 | a tracked word between drawn spaces stays one word | y28 footer "Page", wr 0.9909 → 0.9933 |
| WP46 | lshort's examples stand beside their output (standard profile) | y22 LO product 157 → 154 (wr 0.75 → 0.95); Word 157 → 154 |
| WP47 | README figures from the final run; sentinel's wp42 row | criterion 12 PASS; verdict READY |
| land1 / land1b | the landing set (WP33 + WP38 + WP40, `64a6c47`); a rule inside a just-stacked figure holds the cursor | y21 50 → 49 of 48 (wr 0.80 → 0.88) |
| final1 | the final batch (WP42–WP46, 38b, 39b, 35d, 35e) and the gate re-record | strict gate PASS both lanes |
| final1 notes lift | real footnotes lifted by the refine loop to where the source's ended (`f3da747`, `aaa355e`) | y02 dy_p50 1.03 → 0.74, p20 notes 49 pt low → in place; raw byte-identical |

## Final scorecard (910e6aa inputs, README at 9adf283)

| # | Criterion | Result |
|---|---|---|
| 1 | crash-free | PASS — 0 errors in 365 conversions; 5/5 unsupported refused with typed exit codes |
| 2 | time | PASS — 0 of 90 over in either lane (10 product, 7 raw timed serially) |
| 3 | Word opens with no repair prompt | PASS — 90/90, compatibility mode 14 |
| 4 | promised ≤ 20 pages page-exact, every lane | PASS — 41/41 LibreOffice, Word, Docs |
| 5 | promised > 20 pages | PASS — LibreOffice 21/21, Word 21/21, Docs 18/21 |
| 6 | no char recall < 0.5 or pages off > 20% | PASS — 62/62 every lane |
| 7 | placement, promised ≤ 20 pages | REPORTED — 92.7% every lane |
| 8 | no regression vs the accepted sweep | PASS — 0 worse; y37 waived (32.0 ≤ 33.0); y55 exempt (amendment 4) |
| 9 | editability | REPORTED — 46/62 |
| 10 | fonts | PASS |
| 11 | gated 16 pass both gate lanes | PASS — bound |
| 12 | README numbers | PASS — 8 cited, 0 stale |
| 13 | Docs quality policy per document | REPORTED — LibreOffice 72.6%, Word 72.6%, Docs 67.7% |

## What is open

- **The three Docs long misses (criterion 5 passes without them):** y12 IRS
  Pub 15 (62 pages for 59, wr 0.74), y21 World Development Report (52 for 48,
  wr 0.54) and y22 lshort (169 for 153, wr 0.34). The WP46 readings stay out
  of gdocs because Docs drops letter-spacing.
- **The infra review's post-beta items:**
  - `refine._norm` and the harness normalise text differently;
  - the scorer's chance matches;
  - promote real-producer fixtures into the gate;
  - criterion 8 over the Word rows;
  - fuzz and metamorphic tests.
- **Before 0.3.0b2: the paired-word dy_p50 reading** (amendment 4(e)). Criterion
  8's dy_p50 is a median over whichever words each render matched; y37's
  waiver is the case for reading it over common words. The waiver dies with
  0.3.0b1.
- **y12 p56 at the baseline anchor.** It is still off under the baseline
  refine anchor.
- **y43 and y55 wrap fidelity.** Their pages are bimodal (WP39): the median
  sits on the group the loop cannot align. y55 is exempt under amendment 4,
  not fixed.
- **`expansion_parity_policy` still pins the old (pre-Carlito) fingerprint.**
  The parity floors were not re-measured in the new image (WP32 dry run only).
- **README citations dated 2026-10-04 go stale.** The live gated-16
  qualification (`gdocs-2026-10-04-pass9b-qualification.json`) and the
  example-images run (`readme-examples-2026-10-04.json`) are exactly 7 days old
  against the final inputs. Any input dated 2026-10-12 or later fails
  criterion 12 until a fresh gated-16 live qualification and a new example run
  are cited.
- Open from round 3 and still standing: Word's Compatibility Mode banner (mode
  14 kept on purpose); the Google Docs output is not yet right-to-left.
