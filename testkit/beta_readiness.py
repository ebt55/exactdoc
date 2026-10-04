"""Is exactdoc ready for its first public beta? The bar, against the latest numbers.

    python testkit/beta_readiness.py --runs <dir> [--runs <dir> ...]
    python testkit/beta_readiness.py --raw R.sweep.json --product P.sweep.json \\
        --gdocs rows.jsonl --word word_rows.jsonl --gate <dir> \\
        --accepted A.sweep.json --docx-dir <kept DOCX folder>
    python testkit/beta_readiness.py ... --json readiness.json

A READING of measurements, never a measurement and never a gate: it converts
nothing, renders nothing, uploads nothing, and the CI gate does not call it. It
reads what the measuring tools already wrote --

    quality sweeps   testkit/quality_sweep.py --json (exactdoc.quality-sweep.v1).
                     The profile is read from the payload, so --runs finds the
                     newest full-corpus raw, product and gdocs-profile sweeps.
                     The raw sweep is the LibreOffice lane; the product sweep
                     is read for timing.
    Docs live        rows.jsonl from the live Google Docs sweep, one object per
                     document ({"doc", "src_pages", "out_pages", "char_recall",
                     "word_recall", "dy_p50", ... or "error"}).
    Word             the Word lane's JSONL (WP21): rows shaped like the Docs
                     rows plus open/repair/compat fields. Recognised by a
                     "lane": "word" field or by Word-only keys.
    gate verdicts    lane_raw/verdict.json and lane_product/verdict.json from
                     testkit/runall.py (testkit/batch/ or a copied <run>.batch/).
    accepted sweep   the last raw sweep the coordinator accepted, for the
                     per-document regression check (--accepted).
    kept DOCX        the DOCX files a sweep kept (sweep.sh KEEP_DOCX=1 writes
                     <name>.docx/ beside <name>.sweep.json), for the font census.

-- and prints one line per criterion, PASS, FAIL by N, REPORTED or UNMEASURED,
with the documents that miss. A criterion whose input is missing is
UNMEASURED, never PASS; REPORTED criteria are measured and shown but do not
gate the beta (they gate GA). Exit 0 only when every gating criterion passes.

**Which documents.** Most criteria grade the *promised* documents: the kinds
README.md says work. Expansion documents carry `promised` in
corpus_expansion.json (rule: docs/corpus-expansion.md s14); of the gated 16,
the 13 that the ratified gdocs_quality_policy.json tiers ordinary_digital are
promised. Tiers of the gated documents also come from that policy (c3, c4 and
c5 are designed_stress), not from corpus_manifest.json.

**"FAIL by N"** is the number of offending documents for an all-must-pass
criterion, and for a share criterion the number of further documents that
would have to pass to reach the share, summed over lanes.

**The bar below was RATIFIED by the owner on 2026-10-05** (the independent bar
review's proposal, adopted exactly: \"option A\"); docs/beta-bar.md records each
criterion, its threshold, its data source and why. Criteria 1-6, 8 and 10-12
gate the beta; 7, 9 and 13 are reported for it and gate GA. 0.3.0b1 is not
tagged while any gating criterion fails. Changing a threshold here is changing
a ratified bar: do it only with the owner, and update docs/beta-bar.md in the
same commit.
"""
import argparse
import datetime
import glob
import json
import math
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)

# ----------------------------------------------------------------- the bar
BAR = {
    # 1. crash-free: no conversion error on any document in any input, and
    #    every unsupported document refused with a typed, exit-coded error.
    "max_crashes": 0,
    # 2. time (seconds, the sweep's convert_s)
    "product_flat_s": 60.0,          # product: at most this ...
    "product_flat_pages": 40,        # ... for documents of this many pages or fewer
    "product_s_per_page": 1.5,       # above that, at most this per page
    "raw_s_per_page": 1.0,           # raw: at most this per page
    # 3. Word opens every DOCX with no repair prompt; compatibility mode recorded
    "word_open_share": 1.0,
    # 4. promised documents of `short_pages` or fewer: page-exact in every lane
    "short_pages": 20,
    "short_page_exact_share": 1.0,
    # 5. promised documents over `short_pages`: on `long_share` of them,
    #    |out - src| <= max(long_page_slack, long_page_frac * src) and
    #    word_recall >= long_word_recall
    "long_page_slack": 1,
    "long_page_frac": 0.02,
    "long_word_recall": 0.85,
    "long_share": 0.80,
    # 6. catastrophic floor on promised documents, any lane
    "catastrophic_char_recall": 0.5,
    "catastrophic_page_frac": 0.20,
    # 7. placement on promised short documents -- reported for beta, GA gate
    "placement_word_recall": 0.90,
    "placement_dy_p50": 10.0,
    "placement_share": 0.90,
    # 8. no regression against the accepted sweep, with gate.py's tolerances
    "regression_metrics": ("page_err", "word_recall", "doc_recall",
                           "live_text_cov", "within2pt", "dy_p50"),
    # 9. editability on promised documents -- reported for beta, GA gate
    "edit_textbox_frac": 0.05,
    "edit_one_cell_tables_per_page": 1.0,
    "edit_numpr_frac": 0.90,
    # 11. the gated 16, both lanes
    "gate_lanes": ("raw", "product"),
    "gate_documents": 16,
    # 12. README numbers match the release sweep: a cited evidence file older
    #     than the newest input by more than this many days is stale
    "readme_stale_days": 7,
    # 13. the ratified Google Docs quality policy's per-document thresholds
    #     (testkit/gdocs_quality_policy.json, tier ordinary_digital), read from
    #     that file, on this share of promised documents in the live Docs lane
    #     -- reported for beta, GA gate
    "gdocs_policy_share": 0.90,
    # an input older than the newest input by more than this is flagged stale
    "stale_input_hours": 24,
    "lanes": ("lo", "word", "docs"),
    # Ratified 2026-10-05: these are measured and shown but do not gate the
    # beta; they gate GA (1.0). Every other criterion gates.
    "reported_only": ("placement", "editability", "gdocs-policy"),
    "ratified": "owner, 2026-10-05 (option A: the reviewer's bar exactly)",
}

# 10. Font families every Windows 10/11 + Microsoft 365 install has, or that
# Word itself writes into a new document's font table. Names as fontTable.xml
# spells them, case-insensitive. A family outside this set and outside a README
# "fonts" section is a family a tester's Word may substitute.
STOCK_FONTS = {
    # Windows 10/11
    "Arial", "Arial Black", "Bahnschrift", "Calibri", "Calibri Light", "Cambria",
    "Cambria Math", "Candara", "Cascadia Code", "Cascadia Mono", "Comic Sans MS",
    "Consolas", "Constantia", "Corbel", "Courier New", "Ebrima",
    "Franklin Gothic Medium", "Gabriola", "Gadugi", "Georgia", "Impact",
    "Ink Free", "Javanese Text", "Leelawadee UI", "Lucida Console",
    "Lucida Sans Unicode", "Malgun Gothic", "Marlett", "Microsoft Himalaya",
    "Microsoft JhengHei", "Microsoft New Tai Lue", "Microsoft PhagsPa",
    "Microsoft Sans Serif", "Microsoft Tai Le", "Microsoft YaHei",
    "Microsoft Yi Baiti", "MingLiU-ExtB", "PMingLiU-ExtB", "Mongolian Baiti",
    "MS Gothic", "MS PGothic", "MS UI Gothic", "MS Mincho", "MS PMincho",
    "MV Boli", "Myanmar Text", "Nirmala UI", "Palatino Linotype",
    "Segoe MDL2 Assets", "Segoe Print", "Segoe Script", "Segoe UI",
    "Segoe UI Black", "Segoe UI Emoji", "Segoe UI Historic", "Segoe UI Symbol",
    "SimSun", "NSimSun", "SimSun-ExtB", "Sitka Text", "Sylfaen", "Symbol",
    "Tahoma", "Times New Roman", "Trebuchet MS", "Verdana", "Webdings",
    "Wingdings", "Yu Gothic", "Yu Gothic UI", "Mangal", "Leelawadee",
    # Word's default template font table spells the Japanese faces natively
    "ＭＳ ゴシック", "ＭＳ 明朝",
    # Microsoft 365
    "Aptos", "Aptos Display", "Aptos Narrow", "Aptos Serif", "Aptos Mono",
    "Arial Narrow", "Book Antiqua", "Bookman Old Style", "Century",
    "Century Gothic", "Garamond", "Gill Sans MT", "Rockwell", "Tw Cen MT",
    "Wingdings 2", "Wingdings 3", "Bookshelf Symbol 7",
    "MS Reference Sans Serif", "MS Reference Specialty",
}

PASS, FAIL, REPORTED, UNMEASURED = "PASS", "FAIL", "REPORTED", "UNMEASURED"
_REFUSAL_CODES = {"InteractiveFormError": 19, "PageLimitError": 20,
                  "OcrRequiredError": 17, "UnsupportedInputError": 5}
_INFRA = ("evaluate ", "RoundtripError", "worker: ", "Timeout", "upload")
_WORD_KEYS = ("compat", "compat_mode", "word_version", "repair",
              "repair_prompt", "word_pages")


# ------------------------------------------------------------- the corpus
def _load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def corpus(root=HERE):
    """{doc: {"tier", "pages", "promised", "gated"}} for all 95 documents."""
    out = {}
    try:
        policy = _load_json(os.path.join(root, "gdocs_quality_policy.json"))
        gated_tier = {d: t for t, spec in policy.get("tiers", {}).items()
                      for d in spec.get("documents", [])}
    except (OSError, ValueError):
        gated_tier = {}
    for name, gated in (("corpus_manifest.json", True),
                        ("corpus_expansion.json", False)):
        try:
            docs = _load_json(os.path.join(root, name)).get("documents", {})
        except (OSError, ValueError):
            continue
        for doc, spec in docs.items():
            tier = gated_tier.get(doc) if gated else None
            tier = tier or spec.get("tier", "ordinary_digital")
            if gated:
                promised = tier == "ordinary_digital"
            else:
                promised = spec.get("promised")       # None = unclassified
            out[doc] = {"tier": tier, "pages": spec.get("src_pages"),
                        "promised": promised, "gated": gated}
    return out


# ------------------------------------------------------------- the inputs
def _when(path):
    return datetime.datetime.fromtimestamp(os.path.getmtime(path))


def _profile_kind(profile):
    """'pdfium/standard/none/refine0@240dpi' -> 'raw', etc. None if unknown."""
    parts = (profile or "").split("/")
    if len(parts) < 4:
        return None
    _, out_profile, oracle, rest = parts[:4]
    refine0 = rest.startswith("refine0")
    if out_profile == "standard" and oracle == "none" and refine0:
        return "raw"
    if out_profile == "standard" and oracle == "libreoffice" and not refine0:
        return "product"
    if out_profile == "gdocs" and oracle == "none" and refine0:
        return "gdocs-lo"
    return None


def load_sweep(path):
    data = _load_json(path)
    if data.get("schema") != "exactdoc.quality-sweep.v1":
        raise ValueError("%s is not a quality sweep" % path)
    return data


_NO_DESCEND = ("lane_", "cmp_", "rendered", "_tmp", "qs_", "w_")


def _walk(dirs):
    for d in dirs:
        for root, subdirs, files in os.walk(d):
            subdirs[:] = [s for s in subdirs if not s.startswith(_NO_DESCEND)
                          and not s.endswith(".docx")]
            yield root, subdirs, files


def find_sweeps(dirs, docs):
    """{kind: (path, data)}: the newest sweep per profile covering the corpus.

    "Covering" is at least 90% of the documents a default sweep runs (every
    tier but `unsupported`); a targeted `--only` sweep is not a reading of the
    product.
    """
    want = sum(1 for d in docs.values() if d["tier"] != "unsupported")
    best = {}
    for d in dirs:
        for path in glob.glob(os.path.join(d, "*.sweep.json")):
            try:
                data = load_sweep(path)
            except (OSError, ValueError):
                continue
            kind = _profile_kind(data.get("profile"))
            if kind is None or len(data.get("documents", ())) < 0.9 * want:
                continue
            if kind not in best or os.path.getmtime(path) > os.path.getmtime(best[kind][0]):
                best[kind] = (path, data)
    return best


def load_rows(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _norm_doc(doc, docs):
    doc = os.path.basename(str(doc or ""))
    if doc not in docs and doc + ".pdf" in docs:
        return doc + ".pdf"
    return doc


def row_lane(row):
    if row.get("lane"):
        return str(row["lane"]).lower()
    return "word" if any(k in row for k in _WORD_KEYS) else "docs"


def find_rows(dirs, docs, lane):
    """(path, rows) for the newest JSONL of `lane` covering a fair part of the
    corpus (half for Docs; any document for Word, whose lane is new -- the input line says how many)."""
    want = sum(1 for d in docs.values() if d["tier"] != "unsupported")
    need = 0.5 * want if lane == "docs" else 1
    best = None
    for root, _subdirs, files in _walk(dirs):
        for name in files:
            if not (name == "rows.jsonl" or (name.endswith(".jsonl") and lane in name)):
                continue
            path = os.path.join(root, name)
            try:
                rows = load_rows(path)
            except (OSError, ValueError):
                continue
            mine = [r for r in rows if row_lane(r) == lane and
                    _norm_doc(r.get("doc") or r.get("document"), docs) in docs]
            if len(mine) < need:
                continue
            if best is None or os.path.getmtime(path) > os.path.getmtime(best[0]):
                best = (path, rows)
    return best


def load_gate(path):
    out = {}
    for lane in BAR["gate_lanes"]:
        p = os.path.join(path, "lane_%s" % lane, "verdict.json")
        if os.path.exists(p):
            out[lane] = _load_json(p)
    return out


def find_gate(dirs):
    """(dir, verdicts) for the newest directory holding every lane's verdict."""
    best = None
    for d in dirs:
        for root, subdirs, _files in os.walk(d):
            matched = all("lane_%s" % lane in subdirs for lane in BAR["gate_lanes"])
            subdirs[:] = [s for s in subdirs if not s.startswith(_NO_DESCEND)
                          and not s.endswith(".docx")]
            if not matched:
                continue
            verdicts = load_gate(root)
            if len(verdicts) != len(BAR["gate_lanes"]):
                continue
            newest = max(os.path.getmtime(os.path.join(root, "lane_%s" % lane,
                                                       "verdict.json"))
                         for lane in BAR["gate_lanes"])
            if best is None or newest > best[2]:
                best = (root, verdicts, newest)
    return (best[0], best[1]) if best else None


def find_docx_dir(raw_path):
    """The KEEP_DOCX folder sweep.sh writes beside a sweep, if it exists."""
    if not raw_path:
        return None
    cand = raw_path[:-len(".sweep.json")] + ".docx" if raw_path.endswith(".sweep.json") else None
    return cand if cand and os.path.isdir(cand) else None


# ---------------------------------------------------------------- lane rows
def lane_rows(rows, docs, key_fallback="document"):
    """{doc: normalised row} with src/out pages filled from the manifest."""
    out = {}
    for r in rows or ():
        doc = _norm_doc(r.get("doc") or r.get(key_fallback) or r.get("document"), docs)
        if doc not in docs:
            continue
        n = dict(r)
        n["doc"] = doc
        if "out_pages" not in n:
            for k in ("word_pages", "pages"):
                if isinstance(n.get(k), int):
                    n["out_pages"] = n[k]
                    break
        if "src_pages" not in n and docs[doc]["pages"]:
            n["src_pages"] = docs[doc]["pages"]
        out[doc] = n
    return out


def measured(r):
    return (r is not None and "error" not in r and "refused" not in r and
            isinstance(r.get("src_pages"), int) and isinstance(r.get("out_pages"), int)
            and r.get("src_pages") > 0)


def classify_failure(r):
    """'crash', 'refusal', 'infra' or None for a row."""
    if "refused" in r:
        return "refusal"
    err = r.get("error")
    if not err:
        return None
    err = str(err)
    if err.split(":", 1)[0] in _REFUSAL_CODES:
        return "refusal"
    if err.startswith(_INFRA) or "round trip failed" in err:
        return "infra"
    return "crash"


def _shortfall(k, n, share):
    return max(0, int(math.ceil(share * n - 1e-9)) - k)


def _pct(k, n):
    return "%d/%d = %.1f%%" % (k, n, 100.0 * k / n) if n else "0 documents"


def _short(doc):
    return doc[:-4] if doc.endswith(".pdf") else doc


# ------------------------------------------------------------- the reading
def evaluate(docs, sweeps, lanes, gate, accepted=None, docx_dir=None,
             readme_path=None, now=None):
    """-> {"inputs", "criteria", "verdict", ...}.

    `lanes` is {"lo": rows|None, "word": rows|None, "docs": rows|None} of raw
    row lists (the LibreOffice lane is the raw sweep's documents).
    """
    now = now or datetime.datetime.now()
    criteria = []
    promised = {d for d, s in docs.items() if s["promised"] is True}
    unclassified = sorted(d for d, s in docs.items()
                          if s["promised"] is None and s["tier"] != "unsupported")
    L = {lane: (lane_rows(rows, docs) if rows is not None else None)
         for lane, rows in lanes.items()}
    names = {"lo": "LO raw", "word": "Word", "docs": "Docs live"}

    def crit(num, key, name, status, detail, by=None, misses=None):
        criteria.append({"num": num, "key": key, "criterion": name,
                         "status": status, "by": by, "detail": detail,
                         "misses": misses or []})

    # 1. crash-free --------------------------------------------------------
    crashes, infra, refusals, seen = [], [], {}, 0
    sources = [("%s sweep" % k, v[1].get("documents", ())) for k, v in sweeps.items()]
    sources += [("%s lane" % names[k], rows) for k, rows in lanes.items()
                if rows is not None and k != "lo"]
    for label, rows in sources:
        for r in rows:
            doc = _norm_doc(r.get("doc") or r.get("document"), docs)
            if doc not in docs:
                continue
            seen += 1
            kind = classify_failure(r)
            msg = str(r.get("error") or r.get("refused") or "")
            if kind == "crash":
                crashes.append("%s (%s): %s" % (_short(doc), label, msg[:90]))
            elif kind == "infra":
                infra.append("%s (%s): %s" % (_short(doc), label, msg[:60]))
            elif kind == "refusal":
                refusals.setdefault(doc, set()).add(msg.split(":", 1)[0])
    unsupported = sorted(d for d, s in docs.items() if s["tier"] == "unsupported")
    crashed_unsup = [c for c in crashes if any(c.startswith(_short(u) + " ") for u in unsupported)]
    unseen = [u for u in unsupported if u not in refusals]
    typed = [u for u in unsupported if u in refusals and
             all(c in _REFUSAL_CODES for c in refusals[u])]
    if not seen:
        crit(1, "crash", "crash-free", UNMEASURED, "no sweep or lane rows found")
    else:
        detail = "%d error(s) in %d conversions read; %d/%d unsupported refused " \
                 "with typed exit codes" % (len(crashes), seen, len(typed), len(unsupported))
        if infra:
            detail += "; %d upload/measurement failure(s) not counted" % len(infra)
        if crashes or crashed_unsup:
            status, by = FAIL, len(crashes)
        elif unseen:
            status, by = UNMEASURED, None
            detail += "; not exercised: %s" % ", ".join(_short(u) for u in unseen)
        else:
            status, by = PASS, None
        crit(1, "crash", "crash-free", status, detail, by,
             crashes + ["(not counted) " + i for i in infra])

    # 2. time ---------------------------------------------------------------
    parts, offenders, unmeasured = [], [], []
    for kind, limit_of in (
            ("product", lambda p: BAR["product_flat_s"] if p <= BAR["product_flat_pages"]
             else BAR["product_s_per_page"] * p),
            ("raw", lambda p: BAR["raw_s_per_page"] * p)):
        if kind not in sweeps:
            unmeasured.append(kind)
            parts.append("%s: no full sweep" % kind)
            continue
        # Unsupported documents are refused in normal use; a sweep converts
        # them only because it lifts the page cap (--max-pages 0).
        rows = [r for r in sweeps[kind][1].get("documents", ())
                if isinstance(r.get("convert_s"), (int, float)) and r.get("src_pages")
                and docs.get(r.get("document"), {}).get("tier") != "unsupported"]
        slow = sorted(((r["convert_s"] - limit_of(r["src_pages"]), r) for r in rows
                       if r["convert_s"] > limit_of(r["src_pages"])),
                      key=lambda t: -t[0])
        parts.append("%s: %d of %d over" % (kind, len(slow), len(rows)))
        offenders += ["%s %s %.0fs for %d pages (limit %.0fs)" % (
            kind, _short(r["document"]), r["convert_s"], r["src_pages"],
            limit_of(r["src_pages"])) for _, r in slow]
    status = FAIL if offenders else (UNMEASURED if unmeasured else PASS)
    crit(2, "time", "time: product <=%gs up to %d pages, <=%gs/page above; raw <=%gs/page"
         % (BAR["product_flat_s"], BAR["product_flat_pages"],
            BAR["product_s_per_page"], BAR["raw_s_per_page"]),
         status, "; ".join(parts) + " (sweeps run documents in parallel, so "
         "their times are upper bounds)", len(offenders) or None, offenders)

    # 3. Word opens cleanly --------------------------------------------------
    W = L.get("word")
    if not W:
        crit(3, "word-open", "Word opens every DOCX with no repair prompt",
             UNMEASURED, "no Word-lane rows (WP21)")
    else:
        bad, unrecorded, compat = [], [], {}
        for doc, r in sorted(W.items()):
            opened = next((r[k] for k in ("opened", "open", "open_ok", "ok") if k in r), None)
            repair = next((r[k] for k in ("repair_prompt", "repair", "repaired",
                                          "needs_repair") if k in r), None)
            mode = next((r[k] for k in ("compat", "compat_mode", "compatibility_mode")
                         if k in r), None)
            compat[str(mode)] = compat.get(str(mode), 0) + 1
            if opened is False or repair is True:
                bad.append("%s opened=%s repair=%s" % (_short(doc), opened, repair))
            elif opened is None or repair is None:
                unrecorded.append(_short(doc))
        detail = "%d rows; compatibility modes %s" % (
            len(W), ", ".join("%s x%d" % kv for kv in sorted(compat.items())))
        if unrecorded:
            detail += "; open/repair not recorded for %d" % len(unrecorded)
        status = FAIL if bad else (UNMEASURED if unrecorded else PASS)
        crit(3, "word-open", "Word opens every DOCX with no repair prompt",
             status, detail, len(bad) or None, bad + ["(not recorded) " + u for u in unrecorded])

    # 4-7. promised, per lane ------------------------------------------------
    def per_lane(test, subset, share, num, key, name, reported=False):
        lines, misses, by, missing = [], [], 0, []
        for lane in BAR["lanes"]:
            rows = L.get(lane)
            if rows is None:
                missing.append(names[lane])
                lines.append("%s unmeasured" % names[lane])
                continue
            group = [rows[d] for d in sorted(subset) if measured(rows.get(d))]
            absent = len([d for d in subset if not measured(rows.get(d))])
            ok = [r for r in group if test(r)]
            bad = [r for r in group if not test(r)]
            short = _shortfall(len(ok), len(group), share)
            by += short if share < 1 else len(bad)
            lines.append("%s %s%s" % (names[lane], _pct(len(ok), len(group)),
                                      " (%d not measured)" % absent if absent else ""))
            misses += ["%s %s" % (names[lane], m) for m in
                       (describe(r) for r in bad)]
        failing = by > 0
        if reported:
            status = REPORTED
            note = "would %s for GA" % ("FAIL by %d" % by if failing else
                                        ("be UNMEASURED" if missing else "PASS"))
            lines.append(note)
        else:
            status = FAIL if failing else (UNMEASURED if missing else PASS)
        crit(num, key, name, status, "; ".join(lines), by or None, misses)

    def describe(r):
        bits = ["%s->%s pages" % (r.get("src_pages"), r.get("out_pages"))]
        for k, f in (("word_recall", "wr %.2f"), ("char_recall", "cr %.2f"),
                     ("dy_p50", "dy50 %.1f")):
            if isinstance(r.get(k), (int, float)):
                bits.append(f % r[k])
        return "%s (%s)" % (_short(r["doc"]), ", ".join(bits))

    short_docs = {d for d in promised if (docs[d]["pages"] or 0) <= BAR["short_pages"]}
    long_docs = promised - short_docs
    per_lane(lambda r: r["src_pages"] == r["out_pages"], short_docs,
             BAR["short_page_exact_share"], 4, "short-exact",
             "promised <=%d pages: page-exact in every lane (%d documents)"
             % (BAR["short_pages"], len(short_docs)))
    per_lane(lambda r: abs(r["out_pages"] - r["src_pages"]) <= max(
                 BAR["long_page_slack"], BAR["long_page_frac"] * r["src_pages"])
             and (r.get("word_recall") or 0) >= BAR["long_word_recall"],
             long_docs, BAR["long_share"], 5, "long-close",
             "promised >%d pages: |dpages|<=max(%d,%g%%) and word_recall>=%.2f on >=%d%% (%d documents)"
             % (BAR["short_pages"], BAR["long_page_slack"], 100 * BAR["long_page_frac"],
                BAR["long_word_recall"], round(100 * BAR["long_share"]), len(long_docs)))
    per_lane(lambda r: not ((r.get("char_recall") is not None and
                             r["char_recall"] < BAR["catastrophic_char_recall"]) or
                            abs(r["out_pages"] / r["src_pages"] - 1) > BAR["catastrophic_page_frac"]),
             promised, 1.0, 6, "catastrophic",
             "promised: none with char_recall<%.1f or |dpages|>%d%%, any lane (%d documents)"
             % (BAR["catastrophic_char_recall"], round(100 * BAR["catastrophic_page_frac"]),
                len(promised)))
    per_lane(lambda r: (r.get("word_recall") or 0) >= BAR["placement_word_recall"]
             and (r.get("dy_p50") if r.get("dy_p50") is not None else 1e9) <= BAR["placement_dy_p50"],
             short_docs, BAR["placement_share"], 7, "placement",
             "placement, promised <=%d pages: word_recall>=%.1f and dy_p50<=%gpt on >=%d%%"
             % (BAR["short_pages"], BAR["placement_word_recall"], BAR["placement_dy_p50"],
                round(100 * BAR["placement_share"])), reported=True)

    # 8. no regression --------------------------------------------------------
    if not accepted or "raw" not in sweeps:
        crit(8, "regression", "no regression against the accepted sweep (gate.py tolerances)",
             UNMEASURED, "no accepted sweep given (--accepted)" if not accepted
             else "no current raw sweep")
    else:
        try:
            sys.path.insert(0, HERE)
            import gate as _gate
            metrics, tolerance = _gate.METRICS, _gate.tolerance
        except Exception as e:                      # pragma: no cover
            metrics, tolerance = None, None
            err = "%s: %s" % (type(e).__name__, e)
        if metrics is None:
            crit(8, "regression", "no regression", UNMEASURED,
                 "gate.py could not be imported (%s)" % err)
        else:
            base = {r["document"]: r for r in accepted[1].get("documents", ())}
            worse = []
            for r in sweeps["raw"][1].get("documents", ()):
                b = base.get(r.get("document"))
                if not b:
                    continue
                if classify_failure(r) == "crash" and classify_failure(b) != "crash":
                    worse.append("%s now crashes" % _short(r["document"]))
                    continue
                if not (measured(dict(r, doc=r["document"])) and
                        measured(dict(b, doc=b["document"]))):
                    continue
                for m in BAR["regression_metrics"]:
                    spec = metrics.get(m)
                    if spec is None:
                        continue
                    if m == "page_err":
                        cur = abs(r["out_pages"] - r["src_pages"])
                        ref = abs(b["out_pages"] - b["src_pages"])
                    else:
                        cur, ref = r.get(m), b.get(m)
                    if not isinstance(cur, (int, float)) or not isinstance(ref, (int, float)):
                        continue
                    tol = tolerance(spec, ref)
                    delta = (ref - cur) if spec["dir"] == "higher" else (cur - ref)
                    if delta > tol + 1e-12:
                        worse.append("%s %s %.4g -> %.4g (tolerance %.3g)"
                                     % (_short(r["document"]), m, ref, cur, tol))
            regressed = sorted({w.split(" ", 1)[0] for w in worse})
            crit(8, "regression", "no regression against the accepted sweep (gate.py tolerances)",
                 FAIL if worse else PASS,
                 "%d document(s) worse than %s" % (len(regressed), os.path.basename(accepted[0])),
                 len(regressed) or None, worse)

    # 9. editability (REPORTED) ----------------------------------------------
    if "raw" not in sweeps:
        crit(9, "editability", "editability, promised documents", REPORTED,
             "unmeasured: no raw sweep")
    else:
        bad, n = [], 0
        for r in sweeps["raw"][1].get("documents", ()):
            if r.get("document") not in promised or "editability" not in r:
                continue
            n += 1
            e = r["editability"]
            why = []
            if (e.get("textbox_frac") or 0) > BAR["edit_textbox_frac"]:
                why.append("textbox_frac %.2f" % e["textbox_frac"])
            if (e.get("one_cell_tables_per_page") or 0) > BAR["edit_one_cell_tables_per_page"]:
                why.append("one-cell tables %.2f/page" % e["one_cell_tables_per_page"])
            if e.get("numpr_frac") is not None and e["numpr_frac"] < BAR["edit_numpr_frac"]:
                why.append("numpr_frac %.2f" % e["numpr_frac"])
            if why:
                bad.append("%s (%s)" % (_short(r["document"]), ", ".join(why)))
        crit(9, "editability", "editability, promised: textbox_frac<=%.2f, one-cell "
             "tables<=%g/page, numpr_frac>=%.1f where lists exist"
             % (BAR["edit_textbox_frac"], BAR["edit_one_cell_tables_per_page"],
                BAR["edit_numpr_frac"]), REPORTED,
             "%s pass (LO raw sweep); would %s for GA" % (
                 _pct(n - len(bad), n), "FAIL by %d" % len(bad) if bad else "PASS"),
             len(bad) or None, bad)

    # 10. fonts ---------------------------------------------------------------
    readme_fonts = _readme_fonts(readme_path)
    if not docx_dir or not os.path.isdir(docx_dir):
        crit(10, "fonts", "fonts: every declared family stock or listed in the README",
             UNMEASURED, "no kept DOCX folder (sweep with KEEP_DOCX=1, or --docx-dir)")
    else:
        census = font_census(docx_dir)
        allowed = {f.lower() for f in STOCK_FONTS | readme_fonts}
        odd = {f: ds for f, ds in census["families"].items() if f.lower() not in allowed}
        detail = "%d DOCX, %d families declared; %d outside the stock set%s" % (
            census["files"], len(census["families"]), len(odd),
            "" if not readme_fonts else " and the README's %d" % len(readme_fonts))
        crit(10, "fonts", "fonts: every declared family stock or listed in the README",
             FAIL if odd else PASS, detail, len(odd) or None,
             ["%s (%d DOCX%s: %s)" % (
                 f, len(ds), "" if f in census["used"] else ", font table only",
                 ", ".join(sorted(_short(d) for d in ds)[:4]))
              for f, ds in sorted(odd.items(), key=lambda kv: (-len(kv[1]), kv[0]))])

    # 11. the gate ------------------------------------------------------------
    name = "the gated %d pass both gate lanes" % BAR["gate_documents"]
    if not gate:
        crit(11, "gate", name, UNMEASURED, "no lane verdicts found")
    else:
        _path, verdicts = gate
        bad = []
        for lane in BAR["gate_lanes"]:
            v = verdicts.get(lane)
            if v is None:
                bad.append("%s: no verdict" % lane)
                continue
            if not v.get("ok"):
                bad.append("%s: %s" % (lane, "; ".join(map(str, v.get("failures", [])))[:200]))
            m = re.search(r"(\d+) document\(s\) measured, (\d+) expected",
                          " ".join(map(str, v.get("notes", []))))
            if m and int(m.group(1)) != BAR["gate_documents"]:
                bad.append("%s: %s documents measured" % (lane, m.group(1)))
        crit(11, "gate", name, FAIL if bad else PASS,
             "both lanes ok" if not bad else "%d problem(s)" % len(bad),
             len(bad) or None, bad)

    # 12. README numbers match the release sweep -------------------------------
    newest = max([_when(p) for p in _input_paths(sweeps, lanes)] or [now])
    if not readme_path or not os.path.exists(readme_path):
        crit(12, "readme", "README numbers match the release sweep", UNMEASURED,
             "README.md not found")
    else:
        stale = readme_staleness(readme_path, newest, L.get("docs"))
        crit(12, "readme", "README numbers match the release sweep",
             FAIL if stale["misses"] else PASS, stale["detail"],
             len(stale["misses"]) or None, stale["misses"])

    # 13. the ratified gdocs policy on promised documents (reported) ----------
    policy = _gdocs_policy_thresholds()
    rows = L.get("docs")
    name = ("ratified Google Docs quality policy on >=%d%% of promised documents "
            "(Docs live)" % round(100 * BAR["gdocs_policy_share"]))
    if not policy or rows is None:
        crit(13, "gdocs-policy", name, REPORTED,
             "unmeasured: %s" % ("no live Docs rows" if policy else
                                 "gdocs_quality_policy.json unreadable"))
    else:
        group = [rows[d] for d in sorted(promised) if measured(rows.get(d))]
        bad = []
        for r in group:
            why = [k for k, rule in policy.items() if not _meets(r, k, rule)]
            if why:
                bad.append("%s (%s)" % (_short(r["doc"]), ", ".join(why)))
        k = len(group) - len(bad)
        short = _shortfall(k, len(group), BAR["gdocs_policy_share"])
        crit(13, "gdocs-policy", name, REPORTED,
             "%s; %d promised not measured live; would %s for GA" % (
                 _pct(k, len(group)), len(promised) - len(group),
                 "FAIL by %d" % short if short else "PASS"),
             short or None, bad)

    gating = [c for c in criteria if c["key"] not in BAR["reported_only"]]
    statuses = [c["status"] for c in gating]
    verdict = ("NOT READY" if FAIL in statuses else
               "INCOMPLETE" if UNMEASURED in statuses else "READY")
    return {"bar": {k: (list(v) if isinstance(v, tuple) else v) for k, v in BAR.items()},
            "ratified": BAR["ratified"], "evaluated": now.strftime("%Y-%m-%d %H:%M"),
            "promised": len(promised), "unclassified": unclassified,
            "criteria": criteria, "verdict": verdict}


def _gdocs_policy_thresholds(root=HERE):
    """The ratified per-document thresholds, read from the policy itself."""
    try:
        policy = _load_json(os.path.join(root, "gdocs_quality_policy.json"))
        return policy["tiers"]["ordinary_digital"]["per_document"]
    except (OSError, ValueError, KeyError):
        return None


def _meets(row, key, rule):
    if key == "page_match":
        value = row.get("page_match", row.get("src_pages") == row.get("out_pages"))
    else:
        value = row.get(key)
    if "equals" in rule:
        return value == rule["equals"]
    if not isinstance(value, (int, float)):
        return False
    if "min" in rule and value < rule["min"]:
        return False
    if "max" in rule and value > rule["max"]:
        return False
    return True


def _input_paths(sweeps, lanes):
    return [v[0] for v in sweeps.values() if v and v[0] and os.path.exists(v[0])]


def font_census(docx_dir):
    """{"files": n, "families": {family: {doc, ...}}, "used": {family, ...}}
    from w:rFonts and the font table of every DOCX under `docx_dir` (static:
    nothing is rendered). `used` holds the families some run actually names;
    the rest are declared in a font table only (a template leftover is still a
    declaration Word reads)."""
    fams, files, used = {}, 0, set()
    rfonts = re.compile(r"<w:rFonts\b([^>]*)>")
    attr = re.compile(r'\bw:(?:ascii|hAnsi|eastAsia|cs)="([^"]+)"')
    table = re.compile(r'<w:font\b[^>]*\bw:name="([^"]+)"')
    for path in glob.glob(os.path.join(docx_dir, "**", "*.docx"), recursive=True):
        try:
            z = zipfile.ZipFile(path)
        except (OSError, zipfile.BadZipFile):
            continue
        files += 1
        doc = os.path.splitext(os.path.basename(path))[0] + ".pdf"
        with z:
            for n in z.namelist():
                if not (n.startswith("word/") and n.endswith(".xml")):
                    continue
                xml = z.read(n).decode("utf-8", "ignore")
                found = set()
                for m in rfonts.finditer(xml):
                    found.update(attr.findall(m.group(1)))
                used.update(found)
                if n == "word/fontTable.xml":
                    found.update(table.findall(xml))
                for f in found:
                    fams.setdefault(f, set()).add(doc)
    return {"files": files, "families": fams, "used": used}


def _readme_fonts(readme_path):
    """Families named in a README section whose heading mentions fonts."""
    if not readme_path or not os.path.exists(readme_path):
        return set()
    with open(readme_path, encoding="utf-8") as fh:
        text = fh.read()
    out = set()
    for m in re.finditer(r"^(#+)[^\n]*\bfonts?\b[^\n]*\n(.*?)(?=^#{1,%d} |\Z)", text,
                         re.I | re.M | re.S):
        out.update(re.findall(r"`([^`]+)`", m.group(2)))
        out.update(re.findall(r"\*\*([^*]+)\*\*", m.group(2)))
    return out


def readme_staleness(readme_path, newest, live=None):
    """Evidence the README cites, its date against the newest input, and the
    one corpus-level sentence the live rows can recompute."""
    if not readme_path or not os.path.exists(readme_path):
        return {"detail": "README.md not found", "misses": []}
    with open(readme_path, encoding="utf-8") as fh:
        text = fh.read()
    cited = sorted(set(re.findall(r"\(((?:docs/evidence|testkit)/[^)\s]+\.json)\)", text)))
    misses, dated = [], 0
    for c in cited:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", c)
        if not m:
            continue
        dated += 1
        when = datetime.datetime.strptime(m.group(1), "%Y-%m-%d")
        age = (newest - when).days
        if age > BAR["readme_stale_days"]:
            misses.append("%s is %d days older than the newest input" % (c, age))
    m = re.search(r"(\d+) of the (\d+) compared came back with exactly the right\s+"
                  r"number of pages", text)
    if m and live:
        rows = [r for r in live.values() if measured(r)]
        exact = sum(1 for r in rows if r["src_pages"] == r["out_pages"])
        if (int(m.group(1)), int(m.group(2))) != (exact, len(rows)):
            misses.append("README says %s of %s live Docs documents page-exact; the "
                          "latest live rows say %d of %d" % (m.group(1), m.group(2),
                                                            exact, len(rows)))
    return {"detail": "%d evidence file(s) cited, %d dated; %d stale or contradicted"
                      % (len(cited), dated, len(misses)), "misses": misses}


# ----------------------------------------------------------------- output
def render(result, inputs, show=8):
    lines = ["exactdoc beta readiness (%s) -- the bar ratified by the owner on "
             "2026-10-05, docs/beta-bar.md" % result["evaluated"], "", "inputs"]
    for label, path, detail, stale in inputs:
        lines.append("  %-13s %s" % (label, path or "not found"))
        if path and detail:
            lines.append("  %-13s %s%s" % ("", detail, "  [STALE]" if stale else ""))
    lines.append("  %-13s %d promised documents%s" % (
        "promised", result["promised"],
        "; unclassified: %s" % ", ".join(result["unclassified"]) if result["unclassified"] else ""))
    lines += ["", "criteria"]
    for c in result["criteria"]:
        st = c["status"] + (" by %d" % c["by"] if c["status"] == FAIL and c["by"] else "")
        lines.append("  %2d %-11s %s" % (c["num"], st, c["criterion"]))
        lines.append("  %2s %-11s %s" % ("", "", c["detail"]))
        for m in c["misses"][:show]:
            lines.append("  %2s %-11s   - %s" % ("", "", m))
        if len(c["misses"]) > show:
            lines.append("  %2s %-11s   ... and %d more" % ("", "", len(c["misses"]) - show))
    counts = {s: sum(1 for c in result["criteria"] if c["status"] == s)
              for s in (PASS, FAIL, UNMEASURED, REPORTED)}
    lines += ["", "verdict: %s  (%d pass, %d fail, %d unmeasured, %d reported)" % (
        result["verdict"], counts[PASS], counts[FAIL], counts[UNMEASURED], counts[REPORTED]),
              "gating: 1-6, 8, 10-12; reported for beta, gating for GA: 7, 9, 13.",
              "0.3.0b1 is not tagged while any gating criterion fails."]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", action="append", default=[],
                    help="folder to search for sweeps, JSONL lanes, gate verdicts "
                         "and kept DOCX (repeatable; also EXACTDOC_RUNS, "
                         "os.pathsep-separated; default testkit/sweep, testkit/batch)")
    ap.add_argument("--raw", help="raw-profile quality sweep (the LibreOffice lane)")
    ap.add_argument("--product", help="product-profile quality sweep (timing)")
    ap.add_argument("--gdocs", help="Google Docs live rows.jsonl")
    ap.add_argument("--word", help="Word-lane JSONL (WP21)")
    ap.add_argument("--gate", help="folder holding lane_raw/ and lane_product/")
    ap.add_argument("--accepted", help="the last accepted raw sweep, for regressions")
    ap.add_argument("--docx-dir", help="kept DOCX folder for the font census "
                                       "(default: <raw sweep>.docx beside it)")
    ap.add_argument("--readme", default=os.path.join(PROJECT, "README.md"))
    ap.add_argument("--json", help="also write the evaluation here")
    ap.add_argument("--all", action="store_true", help="list every offending document")
    a = ap.parse_args(argv)

    dirs = list(a.runs)
    dirs += [d for d in os.environ.get("EXACTDOC_RUNS", "").split(os.pathsep) if d]
    if not dirs:
        dirs = [os.path.join(HERE, "sweep"), os.path.join(HERE, "batch")]
    dirs = [d for d in dirs if os.path.isdir(d)]

    docs = corpus()
    sweeps = find_sweeps(dirs, docs)
    for kind, path in (("raw", a.raw), ("product", a.product)):
        if path:
            sweeps[kind] = (path, load_sweep(path))
    docs_rows = (a.gdocs, load_rows(a.gdocs)) if a.gdocs else find_rows(dirs, docs, "docs")
    word_rows = (a.word, load_rows(a.word)) if a.word else find_rows(dirs, docs, "word")
    gate = (a.gate, load_gate(a.gate)) if a.gate else find_gate(dirs)
    accepted = (a.accepted, load_sweep(a.accepted)) if a.accepted else None
    raw_path = sweeps.get("raw", (None,))[0]
    docx_dir = a.docx_dir or find_docx_dir(raw_path)
    lanes = {"lo": sweeps["raw"][1].get("documents") if "raw" in sweeps else None,
             "docs": [r for r in docs_rows[1] if row_lane(r) == "docs"] if docs_rows else None,
             "word": [r for r in word_rows[1] if row_lane(r) == "word"] if word_rows else None}
    result = evaluate(docs, sweeps, lanes, gate, accepted=accepted,
                      docx_dir=docx_dir, readme_path=a.readme)

    paths = [("raw sweep", sweeps.get("raw")), ("product sweep", sweeps.get("product")),
             ("gdocs-lo sweep", sweeps.get("gdocs-lo")), ("Docs live", docs_rows),
             ("Word lane", word_rows), ("accepted", accepted)]
    stamps = [_when(v[0]) for _, v in paths if v and v[0] and os.path.exists(v[0])]
    newest = max(stamps) if stamps else datetime.datetime.now()
    inputs = []
    for label, v in paths:
        if not v:
            inputs.append((label, None, None, False))
            continue
        path, data = v
        when = _when(path)
        n = len(data.get("documents", ())) if isinstance(data, dict) else len(data)
        prof = data.get("profile", "") if isinstance(data, dict) else ""
        detail = "%s%d rows; modified %s" % (prof + ", " if prof else "", n,
                                             when.strftime("%Y-%m-%d %H:%M"))
        stale = (newest - when).total_seconds() > 3600 * BAR["stale_input_hours"]
        inputs.append((label, path, detail, stale))
    inputs.append(("gate", gate[0] if gate else None,
                   ", ".join("%s %s" % (l, "ok" if v.get("ok") else "FAILED")
                             for l, v in sorted(gate[1].items())) if gate else None, False))
    inputs.append(("kept DOCX", docx_dir, None, False))
    print(render(result, inputs, show=10 ** 6 if a.all else 8))
    if a.json:
        result["inputs"] = [{"input": l, "path": p, "detail": d, "stale": s}
                            for l, p, d, s in inputs]
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=1, sort_keys=True)
    return 0 if result["verdict"] == "READY" else 1


if __name__ == "__main__":
    sys.exit(main())
