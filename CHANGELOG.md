# Changelog

Notable changes to exactdoc. Every quality number in this file is measured in
the canonical environment (`docker/gate.Dockerfile`, pinned by digest) and
traceable to a committed artifact under `docs/evidence/`.

## Unreleased (0.2.0a1, alpha) — porting the live-verified defect catalogue into the converter

**Version renumbered 1.0.1 → 0.2.0a1 (2026-10-04, owner decision).** A 1.x number
promises a stable converter, and this one is changing by the day: the 2026-10-04
programme rewrote parsing geometry, fonts, tables, lists, footnotes, headers and
the refine loop in a single day. Development Status is now "3 - Alpha". The
`v1.0.0` / `v1.0.1` tags stay as history; 1.0 is reserved for the release that
meets the bar in Word, LibreOffice and Google Docs across the expanded corpus.
Nothing was published to PyPI under 1.x, so no installed version sorts above this one.

Between 2026-09-05 and 2026-09-07 a 32-page real report was converted and taken
to CLEAN 1:1 in Google Docs through seven rounds of hand surgery on the output
DOCX, with the converter deliberately frozen. That campaign's defect catalogue
(recorded in the handoff; summarised below) is being ported into the converter
one verified fix at a time, each gated against the frozen 16.

- **Long documents keep each source page on its own page (WP23).** Every
  source page ends in a hard break, so the first page that renders taller
  than its box puts every later page one place late, and word recall --
  words on the right page -- collapses from there: SP 800-88 was one page
  over and scored 0.378. A source-to-render page map found each long
  promised document's FIRST divergent page; the classes, each a general
  rule: *a picture set on a text line or wrapped by a paragraph* is anchored
  at its source position instead of stacked under it (standard profile:
  NIST's withdrawal-notice logo beside "Date updated", SP 800-63B's contents
  numbers drawn as pictures and its wrapped icons; `infer._on_text_line`,
  `_wrapped_by_text`, wp:wrapSquare); *fragments of one row* -- a contents
  number and its entry, two columns of authors, brace labels, a stat
  table's stub and figures -- are one tabbed line, not one line each
  (`infer._fuse_baseline_rows`); *a one-line title* given exactly its own
  width takes the room its line needs from the indent that does not place
  it (`ladder.relieve_one_line`); *preformatted text* is no longer cut at
  its own character grid by the gutter rule (RFC 9000's ASCII-art
  diagrams; `parse_pdfium._same_mono_face`); *a frame's side* running half
  the page is drawn behind the text, not rasterised into the flow at its
  full height (RFC 9110's collected-ABNF box, four pages rendered as
  twelve); *a table of short rows* is not read as two columns
  (`infer._split_unfilled`); *a sidebar's* panel-side cut stands, so it is
  laid out beside the column it was welded to (`infer._sidebar_cut`); *a
  drop cap's* em box no longer swallows the lines beside it as scripts,
  which garbled SP 800-171's chapter openings into "Tsfeednesirtaoivld eaa
  gfyee"; and a contents line keeps its words apart ("1. INTRODUCTION ....
  3", not "1.INTRODUCTION.....3"). Gated: `word/*.xml` byte-identical for
  all 16 under both profiles; gate PASS in both lanes. Raw, 95 documents,
  against integration 16a94de: page-exact 51 -> 58, 19 better, none worse
  (beta criterion 8 PASS); criterion 5 in LibreOffice 4/21 -> 10/21 and in
  Word 4/21 -> 10/21 -- y01 91 -> 80 pages (word recall 0.244 -> 0.965),
  y08 66 -> 65 (0.378 -> 0.988), y09 60 -> 59 (0.340 -> 0.972), y17 202 ->
  194 (0.916 -> 0.976), y27 152 -> 151 (0.460 -> 0.968), y28 22 -> 21
  (0.375 -> 0.989); also y10 38 -> 36 (0.548 -> 0.789), y02 125 -> 120,
  y64 46 -> 44, y22 183 -> 178, y03 58 -> 56, y38 54 -> 53. Google Docs
  output changes (rows, titles, ASCII art, sidebar, drop caps, leaders);
  a probe set against WP19 is prepared.

- **The promised documents that broke the beta bar (WP22).** Each fix is
  for the structure behind the first page that went wrong.
  *EUR-Lex* (y18):
  - a marker item's full first line, arriving as a block of its own, takes
    the rest of the item;
  - a run-in numbered paragraph ("2." at the margin) is one paragraph;
  - a rule drawn as abutting segments, split differently on versos and
    rectos, is signed as one rule. EUR-Lex's head rule is left in the body
    (measured again: in the header it cost the gdocs DOCX 21 pages).
  *LibreOffice Writer Guide* (y36):
  - a recto foot naming the current section is varying furniture, because
    it carries the folio;
  - a full lattice of fill tiles in one drawing cluster is one table;
  - an icon on a band leaves it a box;
  - a white frame behind a picture is not a box;
  - an image placed larger than its clip is cropped to what shows
    (`parse_pdfium._visible_image_box`).
  *Tables and contents* (y24, y26, y03):
  - a rule under every row gives one row per band;
  - same-width rule groups refused by the span bound are cut at their prose
    and read again only as ruled rows or booktabs heads;
  - contents numbers beside leadered entries are row ends, not a column;
  - a spaced leader line with its number is a paragraph with a right stop
    (its dots stay text);
  - grids side by side on one band are one table.
  *Refine*: no page is pushed down while another spills; that push turned
  y18's 145-page round into 150.
  LibreOffice raw, final tree against the integration head, all 90 documents,
  none worse:
  - y18 240 -> 157 pages (char recall 0.583 -> 0.817);
  - y36 36 -> 25 (0.465 -> 1.000);
  - y03 58 -> 53;
  - y24 185 -> 182 (0.683 -> 0.782);
  - y26 216 -> 213 (0.976 -> 0.987);
  - y33 69 -> 62;
  - page-exact 51 -> 52.
  Product:
  - y03 50 -> 46 and y33 63 -> 60, both page-exact;
  - y36 26 -> 25 (0.788 -> 1.000);
  - y18 stays 144;
  - y28 and y40 lose 0.009 and 0.006 char recall at the same page counts.
  Word: y18 250 -> 160 (measured before the head-rule revert), y36 36 -> 25,
  y03 64 -> 53.
  gdocs DOCX rendered by LibreOffice: y18 145 -> 144 (char recall 0.870 ->
  0.988), y36 28 -> 25, y03 55 -> 51.
  Gated: unchanged, gate PASS in both lanes.
  Not fixed: y52 (CJK line packing, which the WP2 footers no longer hide)
  and y24's p44-45 tables cut by page breaks.
  Google Docs is to be flown live (probe set prepared).

- **Microsoft Word is measured, and four Word-only differences are fixed
  (WP21).** `testkit/word_oracle.py` renders DOCX through desktop Word
  (16.0.20430, Office 2024) over COM and scores the render like the live
  Docs sweep; Windows only, never gating, and careful with the owner's Word
  (its own proven instance only, read-only, alerts and macros off, hard
  timeouts, a dialog stops the sweep). Rendering the canonical lanes' own
  DOCX, Word was close to LibreOffice from the start -- raw page-exact 49
  against 51 of 93, product 58 against 62 -- and differed in four places,
  each now written in markup both read alike. *Table edges*: Word 2010
  layout hangs a row left of `tblInd` by its first cell's margin,
  LibreOffice by the table default; the first column's pad is now the
  default and part of the indent (`_lead_pad`), and a border hanging left of
  its text column is kept (`TableEl.hang_left`). Word within-2pt c1 0.612 ->
  0.873, c7 0.443 -> 0.892; LibreOffice c3 0.000 -> 0.797. *Restarts under
  odd/even headers*: Word inserts a blank page before a section restarting
  at its predecessor's parity (y19 115 pages, char recall 0.906);
  `_avoid_parity_blanks` re-bases a one-page or numberless lead, else lets
  the count run on -- y19 114 in Word (0.982). A measured conflict: Word and
  LibreOffice pick header variants by different rules, and LibreOffice pays
  (y19 char recall 0.991 -> 0.982, y25 within-2pt 0.027 -> 0.003). *CJK
  font names in a legacy encoding* (y51's Shift-JIS "ＭＳ ゴシック") are
  decoded (`fonts.decode_font_name`). *Fonts a tester lacks*: the standard
  profile wrote Google-native families (Noto Serif, Roboto Mono, Figtree ...
  on 8 DOCX) and the template's Courier and MS Mincho on all 93; it now
  writes Cambria / Calibri / Courier New for those (`writer_family`) --
  measured equal to Word's own substitution on a stock machine, code kept
  monospaced -- and declares no Courier or Mincho. Non-stock declarations
  across the corpus 19 -> 10, all CJK or complex-script source faces, now
  listed in the README. Word after, raw: page-exact 50, char recall >= 0.95
  on 47 (46), within-2pt 0.239 -> 0.254; product: 59 (58), 55 (54), 0.326 ->
  0.349. LibreOffice raw page-exact 51 = 51, within-2pt 0.228 -> 0.239.
  Not fixed, reported: overflow cascades (y06 +23, y13 +14, y18 +10 pages in
  Word over LibreOffice), CJK line packing (y51 22/12, y52), and
  `compatibilityMode` 15, which drops the "Compatibility Mode" banner but
  re-wraps justified paragraphs (Word within-2pt 0.239 -> 0.193).

- **Google Docs keeps the source's page count: pages at risk are planned
  on Docs' own line model, pages that fit are left alone (WP19).** On the
  2c1c68f live sweep only 27 of 54 ordinary documents were page-exact in Docs.
  Google's own exports of that sweep were aligned word by word with the
  sources, and each element was compared with the writer's model of it
  (`docs/evidence/gdocs-2026-10-05-wp19-diagnosis.json`). Where the pages
  went:
  - rules closing a page (WP18 fixed most);
  - pages the writer knew were over-full but would not absorb past two
    lines;
  - pages predicted to fit with under 15pt to spare, lost 26-46% of the time.

  What Docs adds, measured:
  - Times and Arial lines at 1.150, not 1.144;
  - Roboto Mono 15.3% taller than the table said;
  - the half-point size step;
  - lines mixing families or sizes at max(ascent + gap) + max(descent);
  - inline pictures +3.9pt;
  - the first paragraph's gap dropped after `pageBreakBefore` (1,640 pages).

  Probe 1 corrected all of that on every page. Pages came back:
  - y17 217 -> 195 for 194;
  - y18 258 -> 145 for 144;
  - y08 66 -> 65;
  - y36 36 -> 28;
  - 31/31 short documents page-exact.

  But placement fell on documents that already fit: c1 within-2pt 0.154 ->
  0.064, x05 0.785 -> 0.066, and 01's SSIM dropped under its bound
  (`docs/evidence/gdocs-2026-10-05-wp19-probe1-live.json`). The shipped
  form's errors cancel, so correcting one of a pair moved the words.

  `_gdocs_page_at_risk` now asks whether Docs would set a page, in the
  shipped form, with less than a body line + 2pt to spare:
  - If not, the page is written exactly as before (47 of 90 gdocs DOCX are
    byte-identical to 92c542c).
  - If so, the page's own gaps pay first, taken from the foot of the page up
    so the fewest lines move (`_gdocs_page_plan(legacy=True)`).
  - Only a page those gaps cannot fit is calibrated: true factors,
    mixed-line rule, rule and picture compensation, and code-box sides
    anchored to the page.
  - A page before a blank source page is left alone.
  - An empty 1pt holder that keeps the dropped page-top gap
    (`GDOCS_PAGE_TOP_HOLDER`, +0.22pt live) is built but off pending probe 2.

  The standard profile is byte-identical for all 90 convertible documents.
  Gate PASS in both lanes at the recorded numbers. `harness.page_words` now
  drops the U+200B that Docs' exporter writes at tabs and soft breaks (1.7%
  of exported words).

- **Faster, byte for byte (WP20b).** The writer spent most of its time inside
  python-docx, and the product profile writes once per refine round.
  `exactdoc/_docx_speed.py` replaces three python-docx internals with
  functions that return what they return -- the per-picture id rescan (an
  XPath over the whole part, quadratic), the successor lookup behind every
  property set, and the XPath in every `run.text =` -- and the writer copies
  its layout with a pickle round trip instead of `deepcopy`; the parser's
  white-glyph visibility test uses a grid index instead of every dark glyph.
  `write_docx` on y06 is 39-47% faster; y61's visibility pass 2.4s -> 0.5s.
  Output: `word/*.xml` byte-identical for all 95 documents in the raw and
  gdocs profiles (190 of 190), and the product output of all 8 A/B documents
  identical. Raw sweep (canonical, 6 at a time, under lighter load than its base): total
  869s -> 548s, and no
  document over the beta bar's 1 s/page (was y06, y40, y56, y61), every
  metric unchanged. Product, one conversion at a time, base vs new
  interleaved: y06 388s -> 256s, y13 76 -> 66s, y64 60 -> 53s, y38 49 -> 43s;
  measurement-dominated documents barely move (y12 97s both). Criterion 2
  still fails for the product profile: the refine loop's remaining cost is
  LibreOffice and re-reading the render, which nothing provably equivalent
  shortens. Capping rounds was measured, not shipped: `--refine 1` saves
  21-40% but publishes y12 (promised) at 62 pages for 59 instead of 60, and
  `--refine 2` costs 1-2 pages on five of the seven long ones
  (`docs/evidence/refine-speed-2026-10-05.json`). quality_sweep now records
  `jobs`, because a 6-job sweep's convert_s is 1.4-2.3x a lone conversion's.

- **A first public beta is mechanically ready, nothing published (WP20).**
  *Install*: the wheel installs into a clean virtualenv and converts two gated
  fixtures with no LibreOffice on python:3.9-slim, python:3.12-slim and
  Windows' system Python 3.13 (`word/document.xml` identical across all
  three); the sdist shrank from 149 files to 47 by pruning `tests/`, which
  cannot run without testkit, and `scripts/check_dist.py` now enforces its
  allow-list. Published DOCX files were mode 0600 on Linux and macOS
  (`mkstemp`'s private mode survived `os.replace`); they now get the umask's
  ordinary mode. *CLI*: `--version`; `--diagnose` (producer, page sizes,
  fonts, class and detected layout, no text); one-line errors with a `hint:`
  for a missing file or a folder (new exit 21, was a traceback), a non-PDF or
  empty file (exit 6, says which), an unwritable output (exit 8, checked
  before converting, was a traceback for a read-only folder), and the default
  name landing on an existing DOCX -- usually the Word file the PDF came from
  -- which used to be overwritten silently (exit 3; `--overwrite` now works
  for one file); a progress line on a terminal; `wrote x.docx (31 pages,
  19.4s)`; an internal error asks for a report. *No LibreOffice*: a bare
  `exactdoc file.pdf` now converts in one pass with a note instead of exit 11;
  `--refine N` or `--oracle libreoffice` by name, and `convert()`, keep the
  strict behaviour. *Slowest document*: y06 (126 pages) is linear, not hung --
  122s raw in the container sweep, 2m03s raw and 6m49s through the default
  refine loop on a desktop, where each of four writes costs ~44s in
  python-docx; no timeout was added. *CI*: `install.yml` builds, `twine check
  --strict`s and installs the wheel on ubuntu/windows/macos x Python 3.9/3.12
  and runs a smoke conversion and the unit suite; `release.yml` publishes via
  Trusted Publishing on a `v*` tag, TestPyPI first and verified byte-for-byte
  (inert until the setup in `docs/releasing.md`); an issue form for bad
  conversions. *Beta bar*: the 13-criterion bar the owner ratified on
  2026-10-05 is `docs/beta-bar.md`, and `testkit/beta_readiness.py` reads the
  latest sweeps and lanes against it (PASS / FAIL by N / REPORTED /
  UNMEASURED); every expansion document now says whether README.md promises
  it (`promised`, 49 of 79; rule in corpus-expansion.md §14; the expansion
  policy re-pinned for that metadata alone). Its first reading: NOT READY,
  with 1, 8 and 11 passing and 2, 4, 5, 6, 10 and 12 failing. Two harness
  tests now skip without PyMuPDF and one width test allows 87 on Python <
  3.12, where `sum()` is not compensated. Conversion output is unchanged:
  `word/*.xml` byte-identical for all 16 in both gate lanes (canonical) and in
  the gdocs and raw profiles (32 of 32); gate PASS in both lanes at the
  recorded numbers (product 0.6427 within-2pt, raw 0.4853), 1435 unit tests
  OK, measured on the tree merged with 9cfcbcc
  (`docs/evidence/beta-install-2026-10-05.json`).

- **One overflow no longer costs a whole page (WP18).** Every source page
  ends in a hard break, so whatever closes a page goes over alone when the
  renderer sets the page a point long, and the break then spends a page on
  it. *Running rules*: a rule repeated at one place on 60% of pages, within
  18pt of a running line and with no body text between them, is that line's
  furniture whatever the gap (`infer._repeated_running_rules`). RFC 9110's
  foot rule, 9.2pt over its foot, was a 2pt body paragraph behind a 66pt gap
  closing all 194 pages, and Google Docs set 77 pages that carried nothing
  but it (272 for 194). *The closing element*: a rule, an empty paragraph,
  or a line placed by a gap of three body lines or more keeps one body line
  of clearance from the bottom of the box, paid from its own gap
  (`docxout._guard_page_tail`). That covers y31's cover date, which Docs
  put on a page of its own on both covers, 20 pages for 18. The footer
  model now counts a row's border. Gated: `word/*.xml` byte-identical for
  all 16 under both profiles; gate PASS in both lanes. LibreOffice raw,
  measured on the merged tree: y17 204 -> 202 pages (word recall 0.889 ->
  0.916), y27 155 -> 152 (0.396 -> 0.460), y08 67 -> 66, y18 242 -> 240, no
  document worse; product: y27 152 -> 151, page-exact (0.761 -> 0.968), y17
  203 -> 202, y06 149 -> 148. Google Docs is to be flown live (probe set
  prepared).

- **designed pages stay editable: rounded panels, card rows, side-by-side
  regions, sidebars and CV date gutters (WP13).** A rounded panel is drawn
  with curves, so the parser called it artwork and inference rasterised the
  panel with every paragraph in it: y58_ssa_statement's page 1 was one
  1822x1574px picture (live text 0.119), c1's three KPI cards one picture.
  Both parsers now report a rectangle with rounded corners as a rectangle
  (`model.rounded_rect_bbox`: one subpath, axis-aligned straight edges, 90%
  of its box filled where a disc fills 78.5%). Boxes on one band become one
  card row (`_merge_box_rows`); a box reads its lines as a flow (lists, rows)
  and starts a paragraph where the source broke a line by hand
  (`_forced_break`, one text column only); a line the parser joined across
  two panels is cut at the panel edge when regions take every piece. Regions
  set side by side -- panels in two columns, a picture beside a masthead, a
  column against a drawn rule, a sidebar under the two-column bar's 35% --
  are laid out as such where the two-column path does not fire: equal widths
  as a 2-column section, unequal as a borderless layout table whose cells
  carry the column's own flow (`Cell.blocks`; Google Docs imports only
  equal-width column sections). A CV's date gutter no longer becomes the
  left margin: each dated entry is `date TAB role` hanging at the main
  column (`_gutter_column`); separate items on one baseline at item spacing
  are one tabbed row; a chart's axis numbers ride with the chart, and an
  ornament inside a box is left to the box. The regions read only where
  neither two-column reading (WP12's gutter, the block clusters) claims the
  page. A court caption ruled off over a page that runs on in one column
  (y63) is a box of two cells rather than a section -- the section breaks
  around it cost LibreOffice a later page's footnote room -- and a flush-left
  column's flush-right lines ("Plaintiff,", "Defendant.") are lines of their
  own (`_flush_right_edge`). Measured raw against e17795e (WP12 and WP15
  merged) over 90 documents: page-exact 48 -> 51, the sum of |page ratio -
  1| 16.69 -> 13.46 with no document gaining a page, mean char recall 0.804
  -> 0.826, live text 0.933 -> 0.945, within-2pt 0.229 -> 0.235. y58 4 -> 3
  pages (live text 0.119 -> 0.888), y44 4 -> 3 (char recall 0.59 -> 1.00),
  y46 2 -> 1 (within-2pt 0.000 -> 0.159), y40 14 -> 12, y10 39 -> 38, y64 47
  -> 46, y60 35 -> 34, c5 2 -> 1 (within-2pt 0.800 -> 0.975, past its
  recorded shortfall), c1's cards live (char recall 0.972 -> 1.000,
  within-2pt 0.869 -> 0.873); WP15's targets keep their gains (y28-y36,
  y54; y63 5 pages, recall 1.000, within-2pt 0.087 -> 0.116), WP12's
  y39/y41/y43 and y59 (18 pages) unchanged, and the owner's resume, y29,
  y45, x17 and x18 unchanged in inferred layout. The mean edit score dips
  0.003: panels are one-cell tables, and y46's section-tag rows, one figure
  each since WP15, cut its columns into two sections. Flown live in Google
  Docs (2026-10-04), the first probe found two
  defects, both fixed: a layout row pinned to its region (778pt against a
  786pt body on the shaded-sidebar page) cannot split, and Docs' row padding
  plus its closing paragraph turned one page into three -- a layout row's
  pin now keeps two of its own line pitches and 4pt clear of the page foot
  (`_layout_row_pin`; a nested box drawn to the foot gives up the same
  bottom pad; also capped in y11, y34 and y47, whose raw sweep is
  unchanged); and the gdocs box form (bordered paragraphs) dropped a
  panel's fill -- a filled box now carries `w:shd` on its paragraphs, and a
  filled box the source drew without a stroke has its rails in its own fill
  colour instead of #333333. Standard and raw output of the 16 gated
  documents is unchanged; the gdocs candidate output of 01, 03, c1 and c5
  gains the shading (c1's two callouts and c5's band also lose the dark
  rails). The second probe passed live: the shaded sidebar is one page with
  its fill, c5 2 -> 1 pages (word recall 0.17 -> 0.88), y46 2 -> 1, c1's
  callouts and cards right (SSIM 0.820 -> 0.830), 03 within-2pt 0.209 ->
  0.271, 01 unchanged; y58 stays 4 pages in Docs but its live text rises
  0.12 -> 0.89.
- **Office and Google Docs exports (WP15): a slide is a page, a blank page is
  a page, and pleading paper's line numbers are furniture.** The classes
  people convert most, diagnosed with the line-drift microscope.
  *Slides* (`infer._deck_pages`: landscape pages whose text runs at a median
  14pt or more -- y34's 18pt against 6.7pt for the corpus's only other
  landscape document) are page-locked: each paragraph a `w:framePr` frame at
  its source position, each table a floating `w:tblpPr` table, each picture
  anchored to the page (`wp:anchor`, no wrap); the text stays editable.
  Flowed, a slide stacked its logo, screenshots and callouts under the text
  beside them, and 40 slides rendered 93-98 pages. Behind a new profile
  capability, `anchored` (standard only: Google Docs output keeps the flow,
  and a picture covering 97% of the page stays the writer's full-page rule's).
  *Blank source pages are held* (`docxout._blank_page_holder`): Google Docs
  exports a document's empty pages, and folding y32's away put every word
  after its title page on the wrong page -- except behind a page that
  overflows, where the spill takes the blank page's place (y30's cover).
  *Pleading paper*: the parser splits each line number off the line it
  numbers and keeps a 1-9 column out of the vertical-text pass; inference
  consumes the 1-28 gutter and writes it as one framed header paragraph on
  every page; full-height margin rules no longer set the margins or close
  table lattices; double-spaced text (every step of the block >= 1.6em)
  splits where the next line's first word would have fitted; a heading
  number ending a block rejoins its heading; a joint square is not a box; a
  long rule under a whole span is its underline. *Furniture*: a running
  foot's rule outside the legacy zones goes with the foot into its part
  (y36), and front-matter folios at the arabic folios' place are furniture
  (y30). *Spreadsheets and pictures*: the right edge is also read from the
  rightmost column of figures; two or more figure columns are a table's
  values, not a second text column (y35; y60's text column now outvotes its
  table's); a picture under text or bled into the top or bottom margin is
  anchored (y33's tinted panels, its cover art); graphics side by side are
  one figure; "2.5"-style section numbers glue to their headings. Canonical
  raw sweep, all 90 documents, against the integration head cc1203a:
  page-exact 40 -> 48, word recall 0.622 -> 0.679, char recall 0.768 ->
  0.804, within-2pt 0.217 -> 0.229, |page ratio-1| 0.226 -> 0.185, SSIM
  0.642 -> 0.663. Pages (word recall): y34 93 -> 40 (0.15 -> 0.92), y32
  35 -> 37 (0.26 -> 0.99), y63 9 -> 5 (0.29 -> 0.995), y31 19 -> 18 (0.30
  -> 0.98), y30 35 -> 33 (0.45 -> 0.98), y35 15 -> 14 (0.36 -> 1.00), y33 74
  -> 69 (0.22 -> 0.45), y36 42 -> 36, y28 27 -> 22 (0.30 -> 0.37), y62 27 ->
  20 (0.31 -> 0.72), y43 22 -> 19, y51 14 -> 12 (0.74 -> 0.99); y29 stays
  4/4 at 1.000. Product lane, the 11 office/Docs targets: page-exact 4 -> 8,
  word recall 0.525 -> 0.816, within-2pt 0.120 -> 0.221, |page ratio-1|
  0.157 -> 0.016. Worse, honestly: held blank pages expose inflation the
  dropped ones had hidden -- y24 169 -> 185 (16 blank pages in 180; recall
  0.396 -> 0.300, every page after p46 now at a constant +5 where the head
  drifted from +1 to -10), y21 54 -> 57 (four trailing blanks), y22 178 ->
  184 and y52 61 -> 63 (both with recall up); y64's recall 0.180 -> 0.095
  with a page fewer (one table page set as tabbed rows instead of two
  columns; every other page's layout identical, the drop is its table pages'
  repeated figures matching on other pages); y62 live text 0.805 -> 0.769 (a
  bill's gutter differs page to page, so it is consumed and not printed);
  y34 edit score 0.606 -> 0.450 (its text is in frames); y30's product-lane
  recall 0.982 -> 0.975. The gated 16 write every DOCX XML part identically
  in both profiles. Under the gdocs profile the expansion documents change
  only through the general rules; a probe set for a live pass is prepared,
  not flown. 54 new tests (`tests/test_office_export_classes.py`).
- **gdocs: right-to-left paragraphs are real RTL paragraphs in Google Docs
  (live, 2026-10-04).** WP14's probe set flown live
  ([evidence](docs/evidence/gdocs-2026-10-04-rtl-probe.json)): with `bidi`,
  justified Hebrew lands within 2pt for 94% of words (35% as the visual
  left-to-right equivalent; dx_p50 26.1 -> 0.24pt), and a Hebrew list's
  worst words move 3pt instead of 148pt. Its uniform 3pt offset leaves its
  within-2pt 0.50 -> 0.17. c4, y48 and y49 are unchanged.
  `PROFILE_CAPABILITIES["gdocs"]` gains `bidi`.
- **tables: an indented table no longer grows into the margin; a label too
  wide for its column spans the blank cells beside it.** x14's totals block
  (an indented table, 322pt in) put its amounts 48-52pt into the right
  margin in LibreOffice and Google Docs alike. The width fit funded a
  too-narrow label column from "free room" counted from the container's
  left edge -- room that lay LEFT of the table -- and grew the table to the
  right. The room is now what lies to the table's right
  (`_fit_col_widths`), and a one-line cell that overflows its column spans
  the blank cells beside it when they draw nothing of their own and share
  its top and bottom rules (`_span_into_blank_neighbours`; clustered-edge
  tables only). x14 in LibreOffice: amounts within 3pt of the source (were
  52pt off), the label on one line, the content below within 3.4pt (24pt
  when the label wrapped).
- **gdocs: the other families' line heights re-measured in Google Docs.** The
  same live probe, run over every family in `NATURAL_FACTORS`, found each one
  equal to its font file's own hhea line, with no offset. The table's older
  values sat 0.006 below that, which was the bias of the original four-line
  probe. Courier New (1.133), Georgia, Roboto, Noto Serif/Sans, Verdana,
  Vollkorn and Consolas (1.171) now carry the measured value. Live pass 12b:
  overall pass, 0 blocking findings; c7 within-2pt 0.132 -> 0.409, l1 0.213 ->
  0.227, 03 SSIM up (dy_p50 2.03 -> 2.15pt); the private report stays CLEAN
  32/32 (within-2pt 0.156 -> 0.219). Arial and Times New Roman measure 1.150
  too but stay at 1.144. Setting them alone helped 02 (0.09 -> 0.59) and c2,
  but broke 01's SSIM bound (0.704 -> 0.680) and moved c6 0.34 -> 0.20,
  because the profile's other levers were calibrated against 1.144. They have
  to be corrected together with those levers
  ([evidence](docs/evidence/gdocs-2026-10-04-natural-factors-remeasured.json)).
- **right-to-left and complex scripts (WP14).** Hebrew, Arabic and Persian
  documents converted to about twice their pages with their text in the wrong
  order. *Parser*: lines are reordered by an inverse of the Unicode bidi
  algorithm at each line's base direction (`Line.rtl`), not by reversing RTL
  letters only, so punctuation, numbers (`114، 2026`), Latin islands and
  brackets land where they belong; Word's RTL word spaces (font-less, 1pt,
  not flagged generated: 1,708 in the five RTL documents, none elsewhere) are
  spaces; a space inside a joined Arabic word is dropped (`وتكي يف`); marks
  snap to their letter; Indic spaces PDFium inserts inside a cluster are
  dropped (`डेट ा`). *Inference*: no undecoded-glyph bullets on RTL lines
  (y49: 121, each splitting off a paragraph's last line); RTL paragraphs are
  measured in mirror image, so alignment and indents come out start/end; RTL
  list markers, notes and line joins work from the right edge. *Writer*
  (standard profile, new `bidi` capability): `w:bidi` with start/end
  `jc`/`ind` (probed in the pinned LibreOffice), `w:rtl`,
  `szCs`/`bCs`/`iCs`, `lang/@bidi` and the source's complex-script face in
  `w:cs`; gdocs keeps a visually equivalent left-to-right paragraph until
  `testkit/gdocs_probe_rtl.py` is flown live. Raw lane, all 90 documents
  against a4fca48: only the 7 targets move — pages y47 100 → 89, y48 11 → 10,
  y49 56 → 54, y50 25 → 19, y54 5 → 4; word recall y54 0.06 → 0.66 and y55
  (Thai) 0.06 → 0.84; page-exact 39 → 40, mean |page ratio−1| 0.2867 →
  0.2749. Product lane against 50f7436: y49 49 → 29 pages (char recall
  0.52 → 0.92), y47 73 → 66, y48 9 → 9, y50 15 → 15 (the base's own run
  times out in LibreOffice in refine round 2, twice); CJK y51–y53 identical.
  Gated c4_i18n within-2pt 0.621 → 0.872 in both lanes (better than its
  record; not re-recorded), live text 0.909 → 0.901 (inside tolerance:
  PyMuPDF reads c4's Arabic words in visual order). Worse: y54 product
  within-2pt 0.219 → 0.159, over six times as many matched words. Still
  open: the pinned renderer sets Arabic 27–45% wider than Arial or Noto
  Naskh, raw y49 spills a few lines per page (David → FreeSerif, +2.6%), no
  `w:bidiVisual` tables. 41 new tests.
- **Journal and arXiv papers: two-column pages read from the gutter, display
  maths from its rows (WP12).** The line microscope (docs/deep-dive/theory.md
  §4) on the seven academic papers found the two-column split taken from the most
  populous block cluster: display-maths fragments outnumbered y41's right column,
  the split landed 52pt inside the left one and page 2 rendered one character per
  line; equation numbers at a NeurIPS page's margin passed for a second column;
  full-width floats moved below the columns; a Frontiers title page's sidebar was
  set at the average column width. Now a two-column page is the white band its
  column lines never cross, each LINE is placed left, right or across, and what
  spans the page cuts it into bands in source order (`infer._two_column_gutter`,
  `_gutter_chunks`); a narrow sidebar on its own baselines is a column of its own
  width (`Chunk.col_widths`, written `w:equalWidth="0"`, standard profile only);
  the parser no longer reads a two-column body with inline maths as table rows
  (`_visual_pieces`). A displayed equation is one paragraph per baseline row at
  the row's own pitch with its number on a right tab stop, and glyphs TeX stacks
  over a line (the "~" of a congruence) join that line; Libertine, Biolinum,
  MathTime and txfonts are named. Raw lane against 50f7436, all 95 documents:
  y41 20→10 pages (word recall 0.159→0.523), y39 29→12 (0.195→0.742), y43 27→22,
  y37 38→34, y40 15→14 (0.245→0.408, dy_p50 117→28pt), y42 7, y38 55; also y12
  78→66, y21 72→54, y03 66→59, y06 168→164, y60 37→35. Product lane: y41 19→9,
  y39 26→12, y40 13→10 (page-exact, recall 0.273→0.759), y43 22→18, y37 28→26.
  Means: |page ratio−1| 0.287→0.236, word recall 0.590→0.606, within-2pt
  0.2145→0.2149. Worse: y26 215→216 pages (recall 0.973→0.924) -- its index
  pages already overflow (TeX's spaced leaders re-wrap), and with their headings
  now where the source sets them the overflow costs a page; y64 within-2pt
  0.112→0.062 (recall 0.130→0.180). The 16 gated layouts are identical. Under
  gdocs the inference changes apply too (columns stay equal-width): unflown.
- **gdocs: Calibri-family line heights measured in Google Docs; Word documents
  stop growing there (live, 2026-10-04).** The gdocs profile writes line
  height as a multiple of each family's natural line in Docs
  (`docxout.NATURAL_FACTORS`), and Calibri -- the commonest Word font, which
  the profile writes as Carlito -- was missing: it took the 1.144 default and
  every line rendered 6.7% tall. A live probe (one paragraph per page, 9-12
  lines at 11pt and 9pt) measured Carlito and Calibri at 1.2207, Cambria 1.1724
  and Caladea 1.1500, each its font file's own hhea line
  ([evidence](docs/evidence/gdocs-2026-10-04-natural-factors.json)). With them,
  live A/B: y30 43 -> 32 pages (33 in the source; char recall 0.58 -> 0.80),
  y33 104 -> 78 (60; LibreOffice 74), y02 135 -> 125 (114), y34 95 -> 94; y30's
  and y02's page growth after the WP2 footers came from this, not from the
  footers. Worse: y34 within-2pt 0.185 -> 0.065, y46 0.010 -> 0.000. No gated
  document uses these families.
- **gdocs: the ladder no longer fits locked lines with tracking Google Docs
  discards (live, 2026-10-04).** The ladder pins a re-wrapping paragraph to
  its source lines and makes each pinned line fit by compressing it with
  negative w:spacing -- under every profile. Docs drops w:spacing (x10 flown as
  written, without it, and with it x10: identical exports), so under gdocs each
  compressed line was set at full width and wrapped: locking without fitting,
  which the ladder's own notes measure as worse than flow. `metrics.for_profile`
  now wraps the shaper in `RendererMetrics(honours_tracking=False)` for gdocs;
  the ladder then shapes at natural advances and refuses a lock that only
  compression would fit, and the writer's spill and column predictions use
  the same view. Standard is unchanged. A/B live on the 11 documents with the
  most compression, same tree, the old belief restored for A
  ([evidence](docs/evidence/gdocs-2026-10-04-tracking-ab.json)): page error
  280 -> 276, summed word recall 3.887 -> 4.139, summed dy_p50 425 -> 378pt;
  y24 word recall 0.395 -> 0.604 (dy_p50 16.0 -> 7.3pt), y43 27 -> 26 pages
  (0.185 -> 0.240), y03 69 -> 67 pages, y18 262 -> 260. Worse: y03 word
  recall 0.408 -> 0.390, y60 dy_p50 68.3 -> 70.2pt, y13/y37 -0.001; x10, the
  control, identical.
- **gdocs: contents-page dot leaders are typed, because Google Docs draws no
  tab leaders (live, 2026-10-04).** The live sweep of the expansion corpus
  found x02's contents page back from Docs with all 1,277 leader dots gone,
  only the page numbers left at the right edge: the right tab stop imported,
  its `w:leader="dot"` did not. Typed dots render, so under the gdocs profile a
  contents line now carries the source's own leader, two dots short, before a
  plain right tab that absorbs the rest (`Para.leader_text`, set where
  `infer._leader_para` makes the stop; `docxout._gdocs_typed_leader`, applied
  to a copy). Standard keeps the real leader tab. Flown on all twelve
  expansion documents with leaders, about 516 entries: no page number wrapped,
  and x02's char recall in Docs went 0.766 -> 0.997.
- **The README is written for a first-time reader; the depth moved to
  `docs/`.** The front page is now a pitch, install, a quick start, what
  "editable" means, and what works and what does not yet, shown with real
  before/after images (`docs/images/`, built by `scripts/readme_images.py`
  from the canonical product run recorded in
  `docs/evidence/readme-examples-2026-10-04.json`). THEORY.md, STATUS.md,
  ROADMAP.md, ESCALATION_RULING_LINEBOX.md and the support-matrix SVG moved
  to `docs/deep-dive/` (lower-case names; history follows the renames), and
  the old README's long sections moved, unrewritten, to
  `docs/deep-dive/{limitations,measured-state,how-it-works,licensing}.md` and
  `docs/usage.md`. `docs/README.md` indexes all of it. Converter behaviour is
  unchanged; only comments and one gate message that named a moved file by
  path were edited.
- **Google Docs round trips survive large documents.** y06 (IRS 1040
  instructions, a 9.9 MB DOCX of page images) could not be measured live at
  all: Drive's simple upload carries at most 5 MB, the create call then
  outlived httplib2's default socket timeout while Google converted it, and
  `files.export` refuses a PDF over 10 MB. Both the product oracle
  (`exactdoc/gdocs.py`) and the qualification oracle now upload over 5 MB
  resumably, give Drive calls a 600 s timeout, and fetch a too-large export
  through the Doc's own export link (only on that 403). Each upload carries a
  unique name, so a create the client gave up on is found and deleted rather
  than left in the user's Drive. y06 now round-trips in 113 s (189 pages,
  15 MB) with nothing left behind.
- **A picture that fills the page is placed on the page (live, 2026-10-04).**
  A designed cover or a scanned page kept as its image was written inline at
  612x792 inside the section margins: Google Docs put y28's cover at (73.5,
  39.6), ran it off the right and bottom edges, and its overflow pushed a blank
  page in front of the memo; LibreOffice did the same at (81.1, 38.8). Four
  writer forms were flown live on y28's own DOCX
  ([evidence](docs/evidence/gdocs-2026-10-04-cover-picture.json)): anchored
  behind text at the page origin it lands at (0, 0, 612, 792) in both
  renderers, where a zero-margin section still left it 1.5–9pt off and a
  crop was ignored. Any picture ≥ 97% of the paper in both dimensions now
  takes that form (`docxout._picture_paragraph`), in every profile. It
  touches four of the 95 documents, none gated. Canonical raw: y28 37 → 36
  pages (word recall 0.176 → 0.214), y56 17 → 14 (0.213 → 0.440), y57 29 →
  26 (0.068 → 0.086), char recall and SSIM up on all three, y34 identical;
  within-2pt slips on the three (y28 0.014 → 0.012), all of them documents
  whose pages are already misaligned. Live Docs, y28: 28 → 27 pages, word
  recall 0.255 → 0.300, dy_p50 72.2 → 55.5pt.
- **gdocs: tab-separated lists are real Word lists in Google Docs; footnotes
  stay typed (live, 2026-10-04).** The WP17 probe set was flown through Google
  Docs, then the whole gated corpus, seven list-bearing expansion documents and
  a private 32-page report, each typed vs real
  ([evidence](docs/evidence/gdocs-2026-10-04-lists-notes-probe.json)). Bullets
  and decimal/alpha/roman lists separated by a tab render with every metric
  identical to the typed form — 577 list paragraphs: 71 in eight gated
  documents (c6_long 50), 444 in x03, x09, y17, y24 (253), y28 and y30, 62 in
  the report — and print the source's numbers
  across an interrupted list, so `PROFILE_CAPABILITIES["gdocs"]` now has
  `numbering`. Two Docs rules found on the way: it ignores `w:suff
  space`/`nothing` and draws a tab where the space was, about half an inch
  past the label's indent (c1's run-in "1. text" recommendations 79.6 →
  106.0pt), so under gdocs a list with a
  non-tab level stays typed, whole (`structures.numbering_plan(tab_only=)`);
  and real footnotes sit at the foot of the text area (dy_p90 3.3 → 73.9pt)
  with custom marks and restarts renumbered as automatic ("3" where the source
  says "1"), so footnotes stay typed. Live pass 9b
  ([qualification](docs/evidence/gdocs-2026-10-04-pass9b-qualification.json)):
  overall pass, zero blocking findings, every fidelity metric identical to pass
  8b on all 16 documents; the private report stays CLEAN 32/32.
- **running headers, footers and page numbers (audit finding 3: B1, B2, B3,
  B26).** Parts were built from page 2 alone, so NIST SP 800-171 — whose page
  2 is its title page — had its running head and folios consumed from 111
  pages and written nowhere. They now come from the page carrying the *modal*
  furniture, with `w:titlePg` when page 1 differs (and states its own footer,
  including none) and `w:evenAndOddHeaders` when each parity has its own
  (a slip opinion's verso/recto heads, lshort's folio side). Furniture is
  searched past the fixed 62/64pt bands to 0.2 H where a row carries the
  page's own number in an unbroken chain from the paper edge: RFC footers 105pt
  up, the Supreme Court's head 114pt down. A printed number is a live PAGE
  field when it tracks the physical index at a constant offset (arabic or
  roman; ≥3 pages, 2 with agreeing `/PageLabels`), and a restart or format
  change opens a section stating `w:pgNumType w:start/w:fmt` (y02: blank
  lead-in, roman i…x, arabic from 1). Heads whose text changes by chapter
  (bash, pandoc, lshort, "CHAPTER ONE") are stated per section instead of
  dropped. `margin_t`/`margin_b` never sit inside a part's extent (y17 was
  written with `pgMar top=200tw` under a 35pt header). Measured in the
  canonical LibreOffice on the way: a first-page part with no default part
  beside it shrinks every later page's body, so neither is written alone; the
  bottom reserve now relaxes to the footer's top instead of being refused.
  A footer keeps its parts but never shrinks the one body box below what
  the source body uses on any page (it moves down just enough, floor 18pt,
  only when that frees a 12pt line), and a footer line set beside another
  row joins it instead of stacking (y30's footer was 31.5pt against 18).
  The refine loop spends the footer's distance down to the same floor when
  its render still spills. Measured on the integration tree (64d3e2a/79d2100
  plus WP2), canonical container: gate PASS both lanes at the re-recorded
  floors (product 16/16, <2pt 0.6019; raw 15/16, 0.4568; per-document lines
  identical to the integration tree), gated outputs byte-identical except
  02/03's `pgMar` bottom. Raw sweep, 90 measured, against 64d3e2a: rendered
  pages 3330 → 3236, mean |ratio−1| 0.3095 → 0.2926, word recall 0.5796 →
  0.5872, doc recall 0.9157 → 0.9192; y17 210 → 204 (recall 0.341 → 0.889),
  y22 223 → 182, y18 264 → 242, y28 37 → 28, y06 178 → 168, y33 82 → 74.
  Open-loop cost that remains: y52 54 → 61, y10 38 → 40, y30 33 → 35, y01
  89 → 92, y02 125 → 127 — documents whose re-wrapped text used the 14pt
  reserve the body had when their folio was not a footer; giving it back
  would move the footer away from where the source prints it. Product
  profile on the 14 most-affected documents: word recall 0.589 → 0.629, doc
  recall 0.934 → 0.949, within-2pt 0.121 → 0.133, pages 979 → 980; y18
  145 → 144 (recall 0.843 → 0.986), y30 recall 0.724 → 0.982, y02 0.918 →
  0.958; y03 53 → 54 and y33 69 → 70 the only page losses.

- **fonts: a family table replaces the descriptor-flag heuristic (audit B12–B15,
  B30, defect catalogue #3/#19).** pdfTeX's Type 1 fonts carry no Serif or
  FixedPitch bit, so `NimbusRomNo9L` (Times' metric clone) became Arial,
  `CMTT10`/`NimbusMonL` code became proportional, `CMBX12` headings lost their
  bold, EUR-Lex's `EUAlbertina` became Arial and `HelveticaNeueLTStd-Roman`
  became Times New Roman ("roman" counted as serif evidence). `fonts.py` now
  names the URW 35, CM/CMU/LM/EC, Helvetica Neue, the Office set and CJK faces
  with class, weight/slant codes (Bd, Blk, Demi, Medi, Ital, CMBX, CMSL…) and a
  target per profile; the parser takes class from it before the flags. The
  standard profile writes Calibri/Cambria by name (gdocs keeps Carlito/Georgia
  until a live pass grades them). Calibri is shaped from Carlito's own widths
  (OFL; was Helvetica's, 8.6% wide), CJK runs name their face in `w:eastAsia`,
  and a run whose emitted width cannot match the source — a half-point size
  (c1's 9.33pt written 9.5) or Courier New for a 0.525em typewriter — carries a
  `w:w` scale from the PDF's own glyph advances, which the ladder shapes with.
  Measured in the canonical container against HEAD. Product lane: y03 62→57
  pages, y18 147→145 (word recall 0.435→0.756), y22 167→166 (recall
  0.261→0.423); c1 within-2pt 0.334→0.678 and c4 0.440→0.621 in both gated
  lanes (gate PASS; product mean within-2pt 0.5274→0.5689); x17/x18 up. Raw
  lane: y03 71→65, y25 361→338, y18 279→265; over all 52 swept documents mean
  within-2pt 0.2107→0.2216, mean |page ratio−1| 0.1517→0.1483, mean word
  recall 0.7445→0.7401 (y24, y22). TeX code blocks now keep their
  line breaks (catalogue #2), which costs raw-lane pages where an unrelated
  overflow had been absorbed by code collapsed into prose — y22 222→229, y24
  168→169 (recall 0.645→0.388 in both lanes, a page-alignment shift), the
  attribution checked by disabling only the name-based monospace class; y06
  202→204 because its cover title is now bold, as drawn. Proportional width
  matching was measured and NOT taken: per-run ratios carry clone-rounding
  noise that moved 02, x05, x06 and x15.

Ported so far, all first verified live on Google's own render:

- **#6 the cells the parser joins.** Adjacent table cells whose gap is under
  the parser's join threshold arrive as one Line; spans keep their own
  boxes, so `build_grid_table` now fragments each line at the drawn column
  bands and assigns spans by their own centres. On the same principle a
  "single line" wider than its column is a straddler, not a need, when the
  column edges were read from the author's grid lines — a 40pt joined
  header span over a 28.5pt column had been driving `_fit_col_widths` to
  shave every neighbour (the family table now holds the drawn pitch to
  0.1pt).
- **#5 (writer half) quote bars are paragraph borders under the gdocs
  profile.** Inside a table cell every quote line rendered 1-2pt taller
  than source in Docs — ~40 lines to a block, the block outgrew its page
  and the spill cascaded. As body paragraphs the same lines carry the
  profile's calibrated line encoding, and the bar is one continuous
  `pBdr` left border (`sz=12 space=8 #BBBBBB`, the live-verified form).
- **#7 (writer half) gdocs table-row levers from the hand campaign's
  round 4**: rows pinned to `trHeight atLeast` = source height; bottom pad
  cut so content lands on `floor(srcH) − 0.75` (Docs rounds every row box
  up to a whole point — that rounding alone measured +1.27pt/row); tcMar
  right trimmed a point (Docs charges the cell border against the text
  area); cell paragraph marks sized to content (inert in Docs, correct for
  Word). Clean rows now land +0.5pt on Google's export.

- **#3 the text column is where the document's own full-width rules end, when
  the text cannot say it in sufficient mass.** A ragged-right document keeps
  its flush edge below the wide-line estimator's 8% membership floor, so the
  rightmost qualifying cluster is an interior band of line ends; on the report
  that cost ~19.5pt of column width and nearly doubled the page count. The
  rule-evidence widener (`_rule_right_edge`) reads the document's rules
  instead — unanimous, 32 rules at one edge — and widens only, never narrows,
  only past the p90 of wide-line ends (a decorative rule overshooting a
  correctly-measured column is rejected: 01_whitepaper's 6pt overshoot moved a
  gated margin before that guard existed, and the Docker gate caught it).
- **#4 Consolas maps to itself.** It was mapped to Courier New, 9% wider, so
  every inline-code run wrapped early. Measured from the font file: 0.550em
  advance (a true monospace), natural factor 1.171 (hhea 1521/−527/350 over
  2048). Google Docs honours a declared Consolas — verified in export spans.
- **#10 a hyphen is only a word break where hyphenation happens.** The join
  dehyphenated every line-end hyphen before a lowercase continuation; on a
  ragged-right report all 41 of them were real text (37 deleted, 4 spaced).
  Dehyphenation now requires a justified paragraph at its wrap edge — a
  ragged-right line keeps its hyphen and joins without a space.
- **#2 a verbatim block keeps its line breaks.** A block whose every glyph is
  monospace is code, not prose; its lines are now separated by breaks the
  writer renders as `w:br`, and break-carrying paragraphs do not merge.
- **#5 quote bars are bars, not pictures.** A 1.5pt-wide vertical rule 100pt+
  tall marking text to its right is a quote bar; the old 1.8pt width floor
  rejected every one (6 then rasterised as ~300pt-tall lines, 56 dropped).
  Vertically-contiguous segments at the same x merge before the quote test.
- **named Heading styles, so Google Docs' outline exists.** Converted
  documents carried only `w:outlineLvl`, which Word's navigation pane reads
  and Google Docs' outline sidebar ignores: every paragraph read "Normal
  text". Headings now carry `Heading 1..6`, with the stock style definitions
  rewritten to explicit zeros (an absent pPr is not a zero pPr — LibreOffice
  supplies its own spacing for a silent "heading 1", which moved a gated
  document's raw lane before the zeros were written).

Measured after the ports, in the canonical container: **gate PASS both lanes
at the recorded baseline numbers** (product 16/16 pages, 0.5274 within-2pt,
0.9588 live text, 1.045pt dy50). The live B13 report went from **58 export
pages before to CLEAN 1:1 at 32** across twelve live rounds — every source
page mapping to exactly one export page, no blanks, no spills, no orphans
(`docs/evidence/gdocs-2026-09-11-b13-align-final.json`) — and the conversion
carries the heading outline the hand-patched file never had. The closing
ports: single-span cell joins split at drawn boundaries by advance
arithmetic (space-guarded), a gdocs column minimum of 22pt funded
proportionally, the single-line pitch bias (−0.38pt), and pageBreakBefore in
place of carrier paragraphs under the gdocs profile — the double-fire class
the hand campaign left "unproven in Docs", now proven absent live. 34 new
unit tests cover the fixes.

Corpus tranche 3 (see `docs/corpus-expansion.md` §12): acquisition reopened for
the two named shortfalls; ten documents fetched, licence-verified and sealed
(16 gated + 41 expansion = 57), adding six producer chains the corpus had
never held — Typst, XeLaTeX, LuaTeX+ConTeXt, pandoc, Arbortext+PDFlib,
Word→PostScript→Distiller — and closing LaTeX-light 1→6, other real-world
1→6. Non-gating, as §7 requires.

Corpus tranche 4 (see `docs/corpus-expansion.md` §13): "what people actually
convert" — 38 licence-verified documents sealed as y28–y65 (16 gated + 79
expansion = 95, 21.9 MB added).

- **Producer chains new to the corpus:** Word, PowerPoint and Excel for
  Microsoft 365 direct exports, Google Docs, Apple Pages, real-world
  LibreOffice, Power PDF, Print To PDF, WeasyPrint, JUST PDF, XPP,
  JasperReports, GPO, three journal pipelines and three arXiv classes.
- **Coverage:** CVs, eight non-Latin scripts and two OCR'd scans.
- **First sweep** (product profile at ec22cbf,
  `docs/evidence/quality-sweep-tranche4-2026-10-04.json`): 38/38 convert, but
  only 10/38 are page-exact. Median ratio 1.38×.
- **Two-column papers** inflate 2.4–2.6× (y41, y39, y42).
- **Panel-backed InDesign text is rasterised wholesale:** y58 keeps 12% live
  text.
- **Scans** go 2.8–2.9× in pages and 53–58× in DOCX size.
- **The word-recall metric cannot grade Thai or Devanagari** (y55 keeps every
  Thai character and scores 0.061).

Non-gating; the expansion parity policy re-pins its corpus hash only.

- **the booklet class, fixed at the root (detection, then flow).** Three
  coordinated changes: the gutter scan reads only narrow lines (≤0.62 of the
  content width) so a spanning caution line can no longer veto a genuine
  three-column page, with an 80pt band-width floor holding narrow byte
  tables out; "wide tail" means crossing the drawn gutter pair, not 62% of
  the page; and runs of same-shape grid pages merge into one continuous
  section whose per-page column breaks drop for natural fill. Measured in
  the canonical container, product lane: y06 294→226 pages (2.33×→1.79×),
  y13 66→59, y12 85→84; gate PASS both lanes unchanged; suite 705 OK.
- **the writer's document flow: a booklet is one flow.** After the run
  merges, ~36 run boundaries each cost a NEW_PAGE section whose leftover
  the renderer cannot refill (~half a page each). Inside the booklet
  signature, same-shape synthetic pages now continue with no break and
  column-shape changes are CONTINUOUS section breaks; the gated corpus
  keeps its page seams unchanged. Two defects the flow's render exposed,
  both fixed: tables inside a column flow size against their column, not
  the page (a table cannot wrap); and pages carrying a table or figure
  wider than a booklet column are excluded from run membership -- y06's
  405pt source worksheets over 3-col instructions were colliding with the
  neighbouring columns' text on six rendered pages. Measured: y06 226 ->
  **198** (2.33x -> 1.57x from the campaign's start), y13 59 -> **53**
  (2.13x -> 1.71x), y12 84 -> 83. Gate PASS both lanes at the recorded
  baseline; suite 719 OK.
- **the booklet document-flow merge, and the page-relative gap cap.** The
  "measured band widths" lever named for y06's residual was disproved by
  its own probe (the snapped bands measure 165.5-166pt; the emission
  writes 165.50), and the decomposition found the +100 pages were pure
  fragmentation on the NON-grid pages: the export carries the same text
  in fewer lines (36,090 vs 40,752) at the exact source pitch. Inside
  booklet-class documents (>= 10 pages with a >=3-col grid and >= 35% of
  the document — the gated 16 carry no >=3-col page, so this cannot fire
  there), `_merge_grid_page_runs` now also merges runs of consecutive
  all-1-col pages (and 2-col runs merge like grid runs), dropping their
  per-page seams while full-width content stays in 1-col sections. Joined
  pages carry gaps capped at 48pt: the fabricated dead space was
  page-relative offsets (a bottom-pinned tail's distance from its page's
  content), 18,300pt of it on the first attempt's render. Measured in the
  canonical container: y06 294->226->**203** (2.33x -> 1.61x total),
  y12 84->**83**, y13 66->59->**58**. Gate: product lane PASS with
  within-2pt **0.5361 -> 0.5445 better** (the cap tightens a gated
  document's own merged 2-col run), raw lane PASS unchanged; the parity
  advisory's "9 regressions" read identically at HEAD code in the same
  restarted container (environment drift, not a code effect). 11 new
  tests.
- **the support matrix is now by producing engine.** One diagram
  (`docs/deep-dive/support-by-engine.svg`, replacing the two per-renderer
  matrices) answers the question a user actually asks — *my PDF came from
  LaTeX / Word / the browser: how will it convert?* Rows are producer
  engines, columns the two output profiles, and the Google Docs column
  carries only live-verified claims (marked `live`) with `†` on engines not
  yet live-tested. The engine rows stand on a fresh canonical sweep of all
  18 real-producer expansion fixtures at e72a900
  (`docs/evidence/engine-sweep-2026-09-11.json`): Word→PDF dialects
  1.03–1.22×, the Distiller dialect and the 214-page GNU Bash manual
  page-exact, LaTeX 0.93–1.35×, RFC/cairo 1.05–1.18×, EUR-Lex +2%, Typst
  page-exact, and the IRS XSL-FO booklets 1.42–1.90× (the designed-stress
  class). The sweep reproduces the committed booklet numbers exactly
  (y06 226, y12 84, y13 59) — an independent confirmation of e72a900.
  Re-swept at the close of the same day, after the document flow, the
  symbol-font fix, the varying-furniture consumption and the wrap
  bracket (`engine-sweep-2026-09-11b.json`, at 621aae6): y06 198, y13
  53, y12 83, y02 128, y21 60, everything else unchanged — the matrix
  and README carry these numbers, and the booklet class stands at
  1.41–1.71×.
- **text fidelity: the characters a reader searches for.** Six defects of
  the real-document catalogue, each traced to where the text is assembled.
  *Line-end hyphens* are decided by the document's own vocabulary
  (`exactdoc/hyphen.py`): the joined form spelled out elsewhere means a break,
  the hyphenated form means a compound, and the document's balance of the two
  is the prior — PDFium returns every line-end hyphen as U+0002 whatever the
  producer drew, so the code point cannot decide. `Con-gress`/`re-turn`
  kept mid-word (pub501 464, SCOTUS 204, 1040i 176, WDR 70 on the 30-page
  cuts) and `singlecorpus`/`middleincome` deleted all go to zero; against the
  opinion's own U+00AD readings 881 of 885 breaks join. `autoHyphenation` now
  follows the same evidence instead of a raw count of 6 (SP 800-63B and
  SP 800-207 lose it, lshort and LuaTeX gain it), sits where CT_Settings puts
  it, adds `doNotHyphenateCaps`, and headings, centred lines and one-line
  paragraphs opt out. *Word spaces*: a style boundary is now tested for a
  space at all (RFC 9110's 26 `MUST NOTgenerate` fusions), and space glyphs
  PDFium drops because each is its own zero-width object are restored where
  they left a gap (`A smaller`, `Cobalt Analytics` on the résumés; README
  #48 closed — the cause was never ink-vs-advance). *Letter-spacing* is
  measured per run and written as `w:spacing` (résumé headings 1.3-1.6pt,
  Chromium body text's 5-7% wider setting, WDR's `O V E R V I E W` closed up
  to `OVERVIEW` when the document spells the word). *Superscripts* take
  their line's size under `vertAlign` (EUR-Lex markers rendered ~3pt;
  standard profile only). *Symbol, Wingdings, ZapfDingbats, MT Extra* PUA
  code points map to their published Unicode (FIPS 180: 398 of 450).
  *Line assembly*: overprinted lines of different sizes stay apart (x07's
  interleaved `4Tr.anCsiti`), a script must be smaller than the glyph it
  attaches to rather than the row's largest (Pub 501's index columns), TeX's
  lowered logo `E` and `2ε` stay in their word (132 broken logos per 30
  pages of lshort), and a one-line paragraph past the inferred column keeps
  room for itself (RFC's `Page N`, one character per line on every page).
  Measured in the canonical container, raw lane, against HEAD: gate PASS
  both lanes with every gated document's line unchanged; expansion
  within-2pt x07 +0.43, x08 +0.41, x09 +0.45, x12 +0.50 (product lane
  +0.49 to +0.75), x17/x18 word recall +0.08, RFC 9110 228 → 221 pages,
  lshort 222 → 216 (product 167 → 163, word recall +0.12). Worse, and why:
  x10 raw 2 → 3 pages (its Table 3 is emitted as stacked one-cell
  paragraphs at HEAD; text set at its true width no longer hides that; the
  product lane keeps 2) and x11 product 2 → 3 (already 4 pages raw at HEAD);
  Pub 501 raw 59 → 60 and small live-text/doc-recall dips on the IRS
  booklets, which the harness charges for removing the discretionary
  hyphens its reference text contains (geometry-only hyphenation restores
  both, measured). 53 new tests. Re-measured after merging WP1/3/4/6/11 and
  tranche 4 (90 documents, raw lane, against the integration head 5ef641a):
  pages −2, summed word recall +0.17, doc recall +0.45, within-2pt +2.63,
  char recall −0.07; worse pages on x10, the IRS booklets (+1 to +3), y37,
  y41 and the y56 scan (+1 each). Two rules were narrowed on that corpus: a
  logo glyph must sit between its neighbours, not under one (fraction
  denominators, y40 15 → 18 pages otherwise), and only short one-line
  paragraphs are pulled back into the column.
- **drawings count as structure only when a reader can see them.** Three
  false-structure defects from weak drawing evidence, fixed in `dialect`
  (visibility) and at two `infer` decision sites:
  Word's per-line `#ffffff` paragraph shading no longer becomes one box
  table per line — a page-coloured, unstroked area fill is dropped unless it
  is visible by contrast with something it touches (a knockout, a zebra row,
  a panel under artwork, part of an image); y01 p21's 7-line paragraph is one
  paragraph again and y01's 111 white boxes are gone. Word's table-border
  joint squares (0.48/1.5pt, flush with the rules they join) are no longer
  promoted to "•": a drawn marker must be ≥ max(2pt, 0.25em) of its line and
  must not touch a rule end — y02 1,286 → 24 bullets (its 24 real ones),
  y11 3,612 → 36, x11's dotted TOC leaders no longer bullet the page numbers;
  Chromium discs (3pt, 0.27–0.29em) are untouched. Paths with zero alpha or
  no paint are dropped before inference reads them. And a vertical rule is a
  quote bar only within 2em of its text, without overhanging it by more than
  1.5em, and not as one side of a drawn frame: y09's page-height margin rule
  had wrapped 56 of 59 pages in a quote table. Raw lane, canonical sweep:
  y09 72 → 67 pages, y01 107 → 103 (word recall 0.184 → 0.199), y02 142 →
  140 (doc recall 0.903 → 0.922), y03 71 → 70, x11 4 → 3; y10 within-2pt
  0.273 → 0.272, everything else identical. Product lane: y09 72 → 65,
  y03 62 → 60, y02 128 → 126, y01 96 → 95. One honest loss: y08's product
  within-2pt 0.336 → 0.321, all of it on p6 (269 words within 2pt → 0).
  The phantom "•" had been that page's first paragraph and so carried its
  `pageBreakBefore`; without it the page opens with the heading box's
  rule after a `w:br` carrier, LibreOffice drops the space before it
  (audit B23) and the page sits 17.5pt high. Disabling only the marker
  rule restores 0.336 exactly. Gated 16: raw DOCX byte-identical to
  before, gate PASS both lanes at the recorded numbers. 30 new tests.
- **résumés: the structure the release bar names.** Five defects on the
  owner's résumé and x17/x18 (defect catalogue #7, #8, #22; design audit
  B16), each a general rule. *Typed list markers* ("• text" in one span,
  "1." "(a)") now open a list item when the flow shows list evidence — a
  second marker at the same x, a hanging indent, or a numbering sequence
  ("5. Section heading" alone stays a heading) — and the item keeps its
  measured hang; x17's fused bullets and RFC 9110's four glued items split.
  *A rule between two lines of one block* cuts the block, so the rule under
  "SUMMARY" is drawn under SUMMARY, not under the summary text. *A lone
  role/date row* takes its tab stop from the document's column of rows
  (same edge, same styles, a label/field style contrast), not the page's.
  *The content edge* may reach the document's rules when two label/field
  rows end there (x17: 486pt column → 509pt). *Body-size section headings*
  — bold caps, one line, at the column edge, tracked or ruled — carry
  Heading styles, so Docs' outline of a résumé exists. x17's 8.92pt dy_p90
  was one paragraph re-wrapping (Chrome's advances run ~4% wide); with the
  column right and a typed item's hang counted as first-line room, the
  ladder locks it. Measured in the canonical container: gate PASS both
  lanes at the recorded numbers, no gated layout changes; x17/x18 product
  dy_p90 8.92 → **2.41/2.42pt**, within2pt 0.102/0.140 → 0.160/0.167;
  expansion+gated product sweep mean within2pt 0.2892 → 0.2935, SSIM
  0.7488 → 0.7503, y17 228 → 224 pages, no product document worse than
  −0.001 within2pt. Worse, honestly: the open-loop raw lane's x17/x18
  within2pt 0.08 → 0.05 (dy_p90 8.92 → 5.9, under that lane's constant
  ~4pt offset), y18 raw 279 → 280 pages, and two lexical hyphens now
  dehyphenated in justified list items (y24, y26) beside nine
  discretionary ones correctly removed.
- **the refine loop: aligned, levered, cheaper, and it cannot lose the
  DOCX.** *Mapping:* source pages map to rendered pages by a monotone
  alignment of lines unique in both documents (LIS), with a diff inside
  each anchored window placing pages that have no unique line; the old
  five-line vote sent RFC 9110's TOC pages 20-170 pages ahead (spill=206 for
  34 surplus pages; round 1 went 228 → 340). *Levers:* each spilled page's
  overflow is read off the render and spent after the unchanged gap step on
  ≤3% line pitch, then ≤50% of table cell top/bottom pads; push-down offsets
  are capped at the room the render shows; the published round's spend is
  reported. *Cost:* the source is read once, figure clips rasterised once,
  one private LibreOffice profile per loop (fresh profiles cost 7-11s a
  render on Windows against 3.5-4s kept; a persistent soffice measured no
  better and is not used), and two quadratic scans in PDFium line grouping
  are gone (page_lines + IR fingerprint-identical on all 94 fixtures;
  page_lines 776 → 455s for the corpus). *Robustness:* a LibreOffice that
  crashes, hangs or writes nothing no longer fails the conversion — the
  best measured round (or the open-loop DOCX) is published and
  `OracleDegradedWarning` raised before publication (escalate it for the old
  all-or-nothing contract; the gate and sweep do); the CLI exits 0 with a
  stderr warning, `convert_result()` returns the `ConversionResult`.
  Absent LibreOffice is still exit 11. The profile lives under a short
  root: ≥ ~160-char profile paths crash soffice on Windows, which failed
  every product conversion under agent TEMP paths. *B23:* inside the loop a
  non-paragraph page opener carries its own `pageBreakBefore`, so
  LibreOffice keeps its page-top gap (probe 84.6 → 184.6pt); open-loop
  writes keep the carrier (kept there, the gap measured as lost slack:
  y17 +3 pages, y27 +2, y03 +3), so the raw lane is byte-identical.
  Measured on the merged tree in the canonical container: gate PASS both
  lanes, product within-2pt 0.5689 → 0.5739 (c6_long 0.90 → 0.98: the old
  mapper had reported a phantom spill on a 7/7 render), raw unchanged
  0.4031; 880 tests. Product sweep (90 documents) against the same tree
  without WP6, run concurrently: conversion time 12,983 → 8,391s (1.55×;
  y06 2,187 → 1,127s, y12 715 → 307s, y01 270 → 137s); 23 documents
  shorter and none longer (y17 223 → 206 pages, y06 199 → 174, y34 86 →
  73, y01 95 → 90, y12 83 → 78, y13 53 → 49, y02 126 → 122), page-exact
  47 = 47; mean within-2pt 0.199 → 0.205, word recall 0.621 → 0.632, char
  recall 0.772 → 0.783, SSIM 0.644 → 0.652; y08 within-2pt 0.321 → 0.349
  (the B23 page WP1 recorded as its loss). Worse, and not yet attributed:
  y22 word recall 0.423 → 0.341 and within-2pt 0.034 → 0.022 although it
  is three pages shorter (the harness matches pages by index, so one spill
  moved earlier shifts every page after it -- the shape y02 had before the
  window fill), y59 recall 0.111 → 0.082, small recall dips on y03, y37,
  y52.

- **the parser reads the page a reader sees (design audit WP4: B6–B11,
  B28; defect catalogue #5, #9).** Every coordinate is in the visible
  frame — CropBox origin removed, /Rotate applied, and a page turned to the
  orientation its text reads when /Rotate would leave every line vertical
  (synthetic probes: CropBox baseline −8 → 42, MediaBox origin 92 → 142,
  /Rotate 90 no longer loses its text). Objects inside Form XObjects are
  placed through the form's matrix (a rect at form (0, 752) is at page
  (150, 352)): y47's charts, y13's TIP/CAUTION icons and y03's figures now
  sit where they are drawn instead of piled in a page corner. Text a reader
  does not see is not text: off-page printer's slugs (y06/y12/y13, 38k
  chars that had become the running header), render-mode-3 text (y19's
  invisible line-start spaces), clipped glyphs, 0.01pt duplicates, white on
  the bare page (y21, GPO's white "VerDate … Frm … Sfmt" slug on y61/y62),
  and an icon's own lettering. Except an OCR layer over a scan, which
  becomes the page's editable text with the duplicated scan left out
  (`--ocr-layer image` keeps the picture). Images with an SMask/stencil are
  embedded as PDFium paints them (y20's logo and y01's TOC numbers were
  black boxes); opaque JPEGs pass through as their own stream; parser drops,
  failed figure renders and bad link annotations are counted, not silent;
  a write opens the PDF once for all figure clips; pages of another size
  get their own section (pgSz, w:orient, pgMar). Gated corpus byte-identical
  (raw DOCX, all 16); canonical gate PASS both lanes (product 16/16, <2pt
  0.5689; raw 15/16, 0.4031).
  Raw sweep over all 95, against the integration head it merged: 35 moved,
  mean abs page-ratio error 0.379 → 0.333, char recall 0.708 → 0.720, live
  text 0.935 → 0.939, SSIM 0.596 → 0.604, page-exact 37 → 38. The OCR'd
  scans y56/y57: 32 → 16 and 44 → 29 pages (10 and 16 in the source), char
  recall 0.01/0.13 → 0.53/0.32, DOCX 31.4/73.1 MB → 1.2/3.8 MB; y42 12 → 7
  pages (live text 0.62 → 0.92); y65 page-exact; y06 204 → 198; y03
  within2pt 0.009 → 0.096. Product lane: y06 198 → 189, y13 and y12 page-
  neutral. Worse, honestly: y13 raw 59 → 61 and its word recall 0.24 → 0.21
  (the correctly placed icons in a three-column booklet flow; the icon-
  lettering rule took it back from 64); y39 27 → 28 and y62 26 → 27 —
  correcting a CropBox origin and dropping an invisible slug both remove
  slack an inflating page had been borrowing; y61/y62 doc recall
  0.963/0.913 → 0.956/0.836 because the harness's reference still counts
  the invisible slug's words; y47 doc recall 0.752 → 0.733 as its chart
  labels move into the now correctly placed chart figures. The visibility
  pass costs 15–20% of character extraction; DOCX size rises where black boxes became
  real RGBA images (y01 0.79 → 0.98 MB) and falls where JPEGs pass through
  (y28 1.96 → 1.53 MB, y50 1.55 → 0.84 MB).
- **tables: a cell exists where the author drew one (design audit finding 8,
  B24; defect catalogue #13).** The grid builder made every lattice cell a
  cell with four borders in one style. Missing internal edges are now merges
  (`w:gridSpan`/`w:vMerge`; text on both sides of a missing line and none
  across it vetoes a column merge), text is assigned by merged region, and
  each cell side carries the rule drawn there. The lattice grows over
  text-bearing fill tiles (FIPS 180 Fig. 1 kept 3 of its 5 columns), ignores
  a link underline, keeps only lines some cell ends on, and refuses a framed
  bar chart. Fill-tiled tables are joined across their unshaded rows (c3's
  merged-header table was rasterised and its nested table flattened); a
  shaded header over unruled rows is one table, continued onto the next page
  (x04/x10 "Table 3" was four paragraphs a row); rules tables cut
  parser-joined rows at their gaps (BLS); figure columns are set flush right,
  one value per paragraph (IRS EIC tables broke '1,205' mid-token); striped
  tables carry their own rules, not c3's colour. The parser ends a span (not
  the line) at a forgiven cell gap or a space boxed across one. Row heights:
  LibreOffice 24.2 applies the largest bottom pad of a row to every cell and
  adds the border on top, so each row is written with one top and one bottom
  pad, the offsets moved into space-before and the border width off the
  bottom pad — NIST SP 800-171's tables had grown ~12pt a row. `trHeight
  atLeast` on text rows measured neutral and is not used (THEORY §3.2).
  Raw lane, canonical, all 90 swept documents against the integration head
  5ef641a: pages 3453 → 3374, word recall 0.5620 → 0.5686, doc recall
  0.9106 → 0.9122, within-2pt 0.1413 → 0.1513, SSIM 0.604 → 0.612, edit
  score 0.5823 → 0.5851. y02 140 → 127 pages, y08 83 → 67 (recall 0.247 →
  0.361), y01 103 → 95, y30 37 → 33 (page-exact, recall 0.424 → 0.731), y06
  198 → 183 (doc recall 0.863 → 0.932), y12 88 → 84, y17 223 → 216. Gated:
  both lanes PASS but for c3 *stale* records (doc recall 0.936 → 1.000, live
  text 0.923 → 0.998, raw word recall 0.865 → 1.000); raw within-2pt c1
  0.678 → 0.869, c7 0.557 → 0.892, r1 0.321 → 0.477, 01 0.207 → 0.314.
  Losses: y03 word recall 0.285 → 0.276 (one page shorter; dy50 down, edit
  score up), x10 within-2pt 0.019 → 0.015 (edit 0.685 → 0.677), y42 word
  recall 0.317 → 0.311. 28 new tests (`tests/test_table_merges.py`, one in
  `tests/test_bottom_margin_relief.py`).
- **ordinary browser- and word-processor-printed documents (WP9).** The
  expansion's Chromium, LibreOffice and ReportLab fixtures kept their page
  counts and still landed 15–74pt off. Each root cause was found with the
  line-drift microscope and fixed as a general rule:
  *A contents page is not two columns*: x11's drawn dot leaders became
  bullets, then a right-hand column, and the page split at a 238pt
  "gutter" (→ 3 pages for 2). Drawn leaders become text dots; dense dot
  leaders become title-TAB-number on a right tab stop with a dot leader
  (`w:leader="dot"`); off-page drawings are dropped; a gutter over 30% of
  the content (every genuine one ≤ 0.234) with the page's prose crossing
  between the columns is not a gutter. *The column is at least as wide as
  the lines that wrapped in it* (98th percentile, verbatim and multi-column
  pages excluded, per page size; x05's edge sat 18pt inside a wrapped
  line); right-aligned fields reaching a rule edge on two pages vouch for
  it. *A rule-less table's rows are tabbed paragraphs* (right stops for
  figures), not one welded line or a vertical stack of cells — except a
  row whose stub ends in a dot leader, which no version measured better
  (y64); a block is cut where rows are taken out of it, so headings inside
  a table keep their place. Markers: outlined `circle` bullets (one per
  line, in a column), a lone mark corroborated only by a list column
  elsewhere, never a tombstone flush with a column end (y41's QED squares
  were bullets at the integration head); raised footnote numbers join their
  note, each note its own paragraph. *Chromium sets text ~6.4% wider than
  its fonts' advances*: WP10's parser measures that per span; `tracking.py`
  measures it per face and size and fills only the runs too short for the
  parser (one `Run.tracking`, written once); the ladder predicts with the
  source's tracking, never with its own lock compression.
  Canonical, merged with the integration head (a6dea69): gate both lanes
  at the head's own numbers (product 0.6019, raw 0.4568; every gated DOCX
  part identical to the head's; FAIL only on the head's own stale c3
  records), 1087 tests. Product lane, within-2pt: x02 0.17 → 1.00, x05 0.37
  → 1.00, x11 0.32 → 0.80 (dy_p90 22.2 → 1.3pt), x14 0.15 → 0.65, x09 0.87
  → 0.97, x10 0.86 → 0.91, x04 0.43 → 0.48, y35 0.04 → 0.25 (dy_p50 23.9 →
  3.3); y50 17 → 16 pages (15 in the source), word recall 0.33 → 0.57.
  Raw sweep, all 90 measured: within-2pt 0.185 → 0.215, word recall 0.572 →
  0.580, char recall 0.728 → 0.737, page-ratio error 0.324 → 0.311,
  page-exact 39 → 40, SSIM 0.616 → 0.625; y09 66 → 61 pages, y33 88 → 82,
  y06 186 → 178, y01 95 → 89, x11 3 → 2, y64 within-2pt 0.02 → 0.11.
  Worse, honestly: live text 0.940 → 0.931 and doc recall 0.917 → 0.916 —
  the metric reads a dot leader drawn by a tab as lost text (x02 0.98 →
  0.74, y10, y36, y30) and "◦"+tab as a token (x09 recall 1.00 → 0.97);
  y39's product lane 25 → 26 pages (11 in the source), word recall 0.30 →
  0.21, from one affiliation number now glued to its line on page 1 (the
  layout is otherwise identical; raw unchanged); y50 raw dy_p50 52 → 61;
  y41 raw within-2pt 0.063 → 0.050 though 21 → 20 pages; y30, y60 recall
  −0.012, −0.011 (contents and table rows now tabbed); y35 raw dy_p90 412 →
  444 (dy_p50 73 → 27). Not fixed here: x07's Chrome `position: fixed`
  running header and footer, painted over the body inside the page, need
  detect_hf (WP2).
- **lists are numbering and footnotes are notes (design audit finding 9,
  §15 items 2–3; benchmark gaps 2 and 8).** Every output of every tool in
  the benchmark had 0 `w:numPr` and 0 footnotes. *Lists* (`lists.py`): the
  typed-marker items inference already recognised are read as lists — a
  level is a marker column, format and start come from the marker, and the
  sequence is checked against the renderers' own counters, so a list splits
  wherever they would print a number other than the source's; an ordinal
  needs a sibling at n±1 ("v.⇥Hillery" on SCOTUS is a citation), a dash a
  sibling, and numbered headings stay headings (c6). *Footnotes*
  (`notes.py`): the small type at the page foot, under a rule or a typed
  dash line and in one compact block, opens a note at each mark
  (superscript, a lone raised fragment, or a plain digit where every note
  uses it) and binds only when the page holds exactly one superscript
  reference with that mark; numbers follow the renderer's counter where it
  reproduces the source and are custom marks elsewhere (symbols, SCOTUS's
  dissent restarting at 1). *Writing* (`structures.py`) is a profile
  capability (`options.PROFILE_CAPABILITIES`): standard writes
  numbering.xml and footnotes.xml, gdocs kept both typed (text-identical on
  all 13 documents with notes) until a live pass graded the probe set
  `testkit/gdocs_probe_lists_notes.py` writes (it since has: see the gdocs
  lists entry above). Typed vs numbered renders in
  the canonical LibreOffice: 0 words moved > 0.5pt on x03, x09, x17, x18,
  c1, c6, 01, 04, 05, l1, c8, r1, y17, y28, y30 (y24: 4 of 44,352, ≤ 0.66pt)
  — after designing around three LibreOffice rules: the tab after a label
  goes to the LEVEL's stop, a `w:suff` space does not stretch in a justified
  line, and `w:lvlRestart 0` / lists opening below level 0 misnumber. Its
  footnote area costs 6.2pt beyond the notes (charged to the page model),
  and one footnote anywhere stops it balancing every column section, so a
  document with column sections keeps typed notes (y22: one note on p15
  spilled the two-column contents on p7). The harness counts generated
  labels and note numbers as live text. Raw lane, all 90 swept documents
  against the integration head a6dea69: 4,422 paragraphs in 58 documents
  are real list items (typed markers 3,940 → 983), 162 notes in 10
  documents are real footnotes, edit score 0.5856 → 0.6272; within-2pt
  0.1853 → 0.1854, word recall 0.5721 → 0.5722, page-exact 39 = 39, mean
  |page ratio−1| 0.3238 → 0.3223 (y18 268 → 264, y02 127 → 125, y28 39 →
  37). Worse: live text x05 0.996 → 0.977 and y18/y19/y50 −0.0005 (typed
  separator lines and EUR-Lex's "(¹)" parentheses become the renderer's rule
  and label), word recall y19 −0.005 and x05 −0.004, y28 dy50 +13.7pt with
  two pages fewer. Product lane, the 11 list and note documents: pages
  unchanged, edit score 0.551 → 0.625, word recall −0.001 to −0.005 and SSIM
  ≤ −0.007 on the documents with notes (y18 dy50 −2.5pt). Gate: both lanes
  identical to the integration head
  (only WP16's c3 *stale* findings). 37 new tests.

## 1.0.1 — 2026-08-07

A résumé went through the converter and came out wrong in ways the 16-document
corpus could not see, because it contained no résumé. Adding one
(`x17_resume_twocol`, with `x18_resume_twocol_tnr` as the control that removes
the monospaced run) exposed six defects at once. This release is those fixes and
the fixture that found them.

### Fixed

- **a hyperlink is a property of characters, not of spans.** The writer asked
  whether a span was *mostly* inside an anchor and tagged the whole span on a
  50% majority, so a link covering less than half its span was dropped
  entirely — which is what a contact header does when one word of a longer run
  carries the mailto. Spans now split at anchor boundaries and each character
  carries its own link.
- **a role and a date on one baseline are one row.** Two runs sharing a baseline
  were emitted as two paragraphs, stacking a right-hand date under the role it
  belongs beside. They are now one paragraph with a right-aligned tab stop.
- **the fontTable declares every font emitted, plus an explicit Normal
  typeface.** An undeclared family is not an error in OOXML; it is an
  invitation, and Google Docs accepted it by substituting its theme face —
  Georgia arrived as something else.
- **tracking is not word spacing.** PDFium fabricates space characters inside
  letter-spaced runs, and those were kept as text, so a tracked heading arrived
  with gaps in it. `_drop_tracking_spaces` removes the fabricated ones and
  leaves real spaces alone.
- **a tracking change ends a paragraph.** A letter-spaced line among
  un-letter-spaced ones is a heading; without that boundary it welded to the
  body text beneath it.
- **hashed JSON is byte-pinned to LF in `.gitattributes`.** A checkout that
  normalised line endings produced a different digest from the one recorded,
  and it failed in both directions — a clean tree reading as modified, and a
  modified tree reading as clean.
- **CI discovers tests instead of naming five files.** The suite had grown to
  663 while CI still ran five script-style suites by name.

### Measured

Confirmation sweep over 31 expansion documents: 25 unchanged, the résumé pair
improved, and the four other movers shown to be render noise by an IR-identical
control on `x11` that establishes a 2.3% noise floor. `y13`'s tab-stop rows fire
but are invisible at its scale.

`x17`/`x18`, before → after: `dy_p50` 3.13 → **0.38pt**, `dy_p90` 25.43 →
**8.92pt**, `within2pt` 0.0590 → **0.1022**, `mean_ssim` 0.8422 → **0.8733**.
Reviewed live in Google Docs and approved. Both runs are committed:
[docs/evidence/sweep-1.0.1-expansion-2026-08-06.md](docs/evidence/sweep-1.0.1-expansion-2026-08-06.md)
indexes the two result sets and their logs, and records what they do and do not
authenticate.

`word_recall` reads 0.9443 → 0.8719 across the same change, and that is a
**reference artifact rather than a text regression**: the harness reference was
extracted with the same PDFium fragmentation this release fixes, so it holds no
whole heading tokens to match against. The converted document gained the
headings; the yardstick never had them.

### Known limitations, carried

- **#48 — ink-vs-advance space synthesis.** Space insertion measures ink extent
  rather than advance width, so a narrow glyph pair can lose its space
  (`A smaller` → `Asmaller`).
- **#47 — cross-platform byte deltas.** Same input on the same platform gives
  identical bytes; across platforms, 6 of 16 gated fixtures match exactly.
  Documents carrying a rasterised region differ by hundreds of bytes, because
  image encoders are not required to be reproducible across platforms, and four
  image-free documents differ by 2–11 bytes for a reason not yet chased.
- **font-style substitution.** Google Docs renders substitute faces for styles
  it does not have. Parked by owner decision: the fontTable now declares what
  the document uses, and what Docs does with that declaration is Docs'.

## 1.0.0 — 2026-08-06

**High-fidelity PDF → DOCX, tuned for documents that have to survive Google
Docs' importer. Apache-2.0. PDFium (pypdfium2) is the core parser; nothing in a
default install carries a copyleft term.**

The version is 1.0.0 because the release bar is met *and live-validated*: the
converter qualifies against the ratified quality policy in Google Docs itself,
not against a local renderer standing in for it.

### The release gate

Live pass 7, consented, against Google Docs —
[qualification](docs/evidence/gdocs-2026-08-06-pass7-qualification.json) ·
[assessment](docs/evidence/gdocs-2026-08-06-pass7-assessment.json):

- `overall_pass: true`, **zero blocking findings** across the 13 blocking
  documents of the ratified policy
- 16/16 documents uploaded, converted, exported and deleted; zero orphaned
  Drive objects
- the uploaded DOCX were verified byte-identical to what a PyMuPDF-free install
  produces, so the run qualified the product a user gets

Regression gate at the bound baseline, both lanes PASS
([re-record](docs/evidence/cover-band-seed-rerecord-2026-08-06.json)):

| lane | page match | mean within-2pt | mean live text | median dy50 |
|---|---:|---:|---:|---:|
| product | 16/16 | 0.5274 | 0.9588 | 1.045pt |
| raw | 15/16 | 0.3615 | 0.9588 | 1.6pt |

### Licence

Relicensed from AGPL-3.0-or-later to **Apache-2.0**. The migration was gated on
four proofs, all recorded: parser parity ratified, two clean consented Google
Docs passes, the [base-wheel proof](docs/evidence/base-wheel-proof-2026-08-06.json),
and the [licence audit](docs/license-audit.md).

PyMuPDF moved out of the core dependency set into an optional `mupdf` extra.
**Installing that extra does not change output** — both installs produce
identical DOCX content on all 16 gated fixtures, proven by content hash. It
exists only for the legacy parser path and for the parity reference arm, and it
is AGPL-3.0-or-later: adding it changes your obligations for anything you
distribute.

### What changed to get here

- **PDFium replaces PyMuPDF as the shipping parser.** The line and block
  clustering PDFium does not provide is written here (`exactdoc/parse_pdfium.py`).
  Four parity findings at the shipping profile were measured and ratified before
  the swap, not after.
- **Permissive text metrics.** The quality ladder shapes text from the published
  Adobe AFM widths (`exactdoc/_base14_widths.py`, generated by
  `testkit/gen_base14_widths.py`), so it works with no optional extra. It is
  deliberately *not* bug-compatible with MuPDF, whose base-14 lookup is Latin-1
  only and charges the space width for em dashes, curly quotes and 25 other
  WinAnsi codepoints.
- **Cover bands inset from the paper edge are recognised.** A band starting
  7.16pt down was treated as ordinary body content, losing both the full-bleed
  side treatment and the Docs vertical compensation; in Google's own export it
  landed 54.5pt right of source and overflowed the page. See
  [the attribution](docs/evidence/c1-live-attribution-2026-08-06.json).
- **Refusals are typed and have stable exit codes**: interactive forms (19),
  page cap (20), OCR-required (17), and the rest of `exactdoc/errors.py`.
- `--verify` compares one page pair at a time; peak RSS on a 259-page comparison
  fell from 5,340 MB to 237 MB.

### Known limitations

Stated in the README's "Limitations" section, generated from the ratified policy
rather than from recollection. The short version: dense multi-column booklets
inflate their page count, interactive forms and image-only scans are refused
rather than mangled, and roughly 14.6pt of white above a page-one cover band is
Google's own and cannot be removed.

## 0.1.0a1

Pre-release development. See the git history and `docs/evidence/` — the
measurement trail starts well before this changelog does.
