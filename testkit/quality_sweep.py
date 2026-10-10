"""Quality sweep: what does the shipping converter do to real documents?

    python testkit/quality_sweep.py                          # expansion corpus, product profile
    python testkit/quality_sweep.py --corpus both --jobs 8
    python testkit/quality_sweep.py --only y01 y13 --profile raw
    python testkit/quality_sweep.py --json new.json --compare old.json

A measurement, never an authorisation. `runall.py` + `gate.py` answer "did the
gated 16 get worse?"; `parity_expansion.py` answers "do the two parsers agree?".
Neither answers the question a user asks -- *how good is the output on a real
document?* -- over the documents that actually embarrass the product: long
Word exports, LaTeX books, Antenna House booklets, RFCs. The 2026-09-11 engine
sweeps that fed the support matrix (docs/deep-dive/support-by-engine.svg) were
ad-hoc scripts; this is that measurement made repeatable, so an improvement
loop can be judged on it.

Every document is converted once at the selected profile and scored by the
independent harness (`harness.evaluate`, which shares no code with the
converter): page ratio, word recall on the right page, document recall,
within-2pt, drift percentiles, live text and SSIM, plus conversion wall time.
Typed refusals (forms, over-cap, OCR-required) are recorded as refusals, not
failures; `--max-pages 0` is passed so the page cap never hides a document.

Parallelism is per document. Each worker gets a private temp directory before
the harness is imported, because the harness keeps ONE LibreOffice profile in
the temp directory and soffice silently writes nothing when two processes share
a profile.

The payload carries `gating: false`; nothing reads it as a verdict.
"""
import _paths  # noqa: F401  (sets sys.path, finds soffice)
import argparse
import json
import os
import statistics
import sys
import tempfile
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed

import corpus_manifest

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "sweep")
SCHEMA = "exactdoc.quality-sweep.v1"
KEYS = ("src_pages", "out_pages", "page_ratio", "word_recall", "doc_recall",
        "within2pt", "within5pt", "dx_p50", "dy_p50", "dy_p90",
        "live_text_cov", "mean_ssim", "convert_s")


def _profile(name):
    from exactdoc.options import PRODUCT, RAW, PDFIUM_GDOCS_CANDIDATE
    return {"product": PRODUCT, "raw": RAW,
            "gdocs": PDFIUM_GDOCS_CANDIDATE}[name]


def select(corpus, only, include_unsupported):
    """[(doc_id, path, tier, producer)] for the chosen corpus, sha-checked."""
    docs = []
    if corpus in ("gated", "both"):
        man = corpus_manifest.load()
        for doc_id, spec in sorted(man["documents"].items()):
            docs.append((doc_id, corpus_manifest.fixture_path(doc_id, man),
                         spec.get("tier", "ordinary_digital"),
                         spec.get("dialect", ""), spec.get("sha256")))
    if corpus in ("expansion", "both"):
        man = corpus_manifest.load_expansion()
        for doc_id, spec in sorted(man["documents"].items()):
            docs.append((doc_id, corpus_manifest.expansion_fixture_path(doc_id),
                         spec.get("tier", "ordinary_digital"),
                         spec.get("dialect", ""), spec.get("sha256")))
    out = []
    for doc_id, path, tier, dialect, sha in docs:
        if only and not any(s in doc_id for s in only):
            continue
        if tier == "unsupported" and not include_unsupported:
            continue
        if sha and os.path.exists(path) and corpus_manifest.sha256(path) != sha:
            raise SystemExit("fixture bytes do not match the manifest: %s" % doc_id)
        out.append((doc_id, path, tier, dialect))
    return out


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_TYPED_MARKER = None


def editability(docx_path, src_pages):
    """How much of the document's editability the conversion spent.

    Fidelity metrics cannot see this: a DOCX made of one absolutely positioned
    text box per line scores perfectly on placement and is useless to edit. So
    count the constructs that make editing fight the user -- exact line heights
    (text added to a paragraph does not grow it), empty spacer paragraphs, soft
    breaks pinned inside paragraphs (re-wrapping is impossible), one-cell layout
    tables, text inside text boxes or frames, typed list markers instead of real
    numbering -- and the ones that help: real lists (`numPr`), heading styles,
    header/footer parts, footnotes.

    `edit_score` folds the penalties into one number in [0, 1]. The weights are
    a judgement, not a measurement, and the components are reported beside it so
    nobody has to trust the fold.
    """
    import re
    import zipfile
    from lxml import etree
    global _TYPED_MARKER
    if _TYPED_MARKER is None:
        _TYPED_MARKER = re.compile(
            r"^\s*([•◦▪‣·\-–—*➤►○●♦]"
            r"|\(?(\d{1,3}|[a-zA-Z]|[ivxlIVXL]{1,5})[.):])\s*$")
    W = _W
    with zipfile.ZipFile(docx_path) as z:
        names = z.namelist()
        root = etree.fromstring(z.read("word/document.xml"))
    body = root.find(W + "body")
    paras = list(body.iter(W + "p"))
    text = lambda el: "".join(t.text or "" for t in el.iter(W + "t"))
    n_text = exact = empty = soft = numpr = typed = headings = 0
    hard = 0
    for p in paras:
        ppr = p.find(W + "pPr")
        t = text(p)
        for b in p.iter(W + "br"):
            ty = b.get(W + "type") or "textWrapping"
            if ty == "page":
                hard += 1
            elif ty == "textWrapping":
                soft += 1
        if ppr is not None and ppr.find(W + "pageBreakBefore") is not None:
            hard += 1
        if not t.strip():
            if p.find(".//" + W + "drawing") is None:
                empty += 1
            continue
        n_text += 1
        if ppr is not None:
            sp = ppr.find(W + "spacing")
            if sp is not None and sp.get(W + "lineRule") == "exact":
                exact += 1
            if ppr.find(W + "numPr") is not None:
                numpr += 1
            st = ppr.find(W + "pStyle")
            if st is not None and (st.get(W + "val") or "").lower().startswith("heading"):
                headings += 1
        runs = p.findall(W + "r")
        if runs and _TYPED_MARKER.match(text(runs[0]) or "") and \
                any(r.find(W + "tab") is not None for r in runs[:3]):
            typed += 1
    all_chars = sum(len(t.text or "") for t in body.iter(W + "t"))
    box_chars = sum(len(t.text or "") for tb in body.iter(W + "txbxContent")
                    for t in tb.iter(W + "t"))
    box_chars += sum(len(text(p)) for p in paras
                     if p.find(W + "pPr") is not None
                     and p.find(W + "pPr").find(W + "framePr") is not None)
    tbls = list(body.iter(W + "tbl"))
    one_cell = 0
    for tb in tbls:
        rows = tb.findall(W + "tr")
        if len(rows) == 1 and len(rows[0].findall(W + "tc")) == 1:
            one_cell += 1
    pages = max(1, src_pages or 1)
    lists = numpr + typed
    c = {
        "exact_frac": round(exact / max(1, n_text), 3),
        "empty_per_page": round(empty / pages, 2),
        "hard_breaks_per_page": round(hard / pages, 2),
        "soft_breaks_per_para": round(soft / max(1, n_text), 3),
        "textbox_frac": round(box_chars / max(1, all_chars), 3),
        "one_cell_tables_per_page": round(one_cell / pages, 2),
        "list_paras": lists,
        "numpr_frac": round(numpr / lists, 3) if lists else None,
        "headings": headings,
        "headers": sum(1 for n in names if re.match(r"word/header\d*\.xml$", n)),
        "footers": sum(1 for n in names if re.match(r"word/footer\d*\.xml$", n)),
        "footnotes": int("word/footnotes.xml" in names),
    }
    score = 1.0
    score -= 0.30 * c["exact_frac"]
    score -= 0.15 * min(1.0, c["empty_per_page"] / 10.0)
    score -= 0.15 * min(1.0, c["soft_breaks_per_para"])
    score -= 0.20 * c["textbox_frac"]
    score -= 0.10 * min(1.0, c["one_cell_tables_per_page"] / 5.0)
    if lists:
        score -= 0.10 * (1.0 - c["numpr_frac"])
    c["edit_score"] = round(max(0.0, score), 3)
    return c


def char_recall(src_pdf, out_pdf, normalise=True):
    """(right-page, anywhere) recall of non-whitespace characters.

    Word recall is meaningless for scripts written without spaces: tranche 4's
    Thai document kept all 5,081 of its characters in the DOCX and scored 0.061
    word recall, because a "word" there is a whole clause and one changed line
    break unmatches it. Characters have no such dependence on segmentation.
    Multiset overlap per page (did the text land on its own page?) and over the
    whole document (did it survive at all?).

    Both sides are read through `harness.recall_text`: symbol-font PUA as the
    characters it encodes and leader runs dropped, as word recall reads them
    (WP29). `normalise=False` is the reading before that, for re-scores.
    """
    import fitz
    from collections import Counter
    import harness

    def pages(path):
        with fitz.open(path) as d:
            return [Counter(ch for ch in harness.recall_text(p, normalise)
                            if not ch.isspace())
                    for p in d]
    s, o = pages(src_pdf), pages(out_pdf)
    total = sum(sum(c.values()) for c in s)
    if not total:
        return None, None
    right = sum(sum((c & o[i]).values()) for i, c in enumerate(s) if i < len(o))
    sa, oa = Counter(), Counter()
    for c in s:
        sa.update(c)
    for c in o:
        oa.update(c)
    return round(right / total, 4), round(sum((sa & oa).values()) / total, 4)


def _work(args):
    doc_id, path, tier, dialect, profile_name, out_root, save_images = args
    tmp = tempfile.mkdtemp(prefix="qs_%s_" % os.path.splitext(doc_id)[0],
                           dir=os.path.join(out_root, "_tmp"))
    os.environ["TMPDIR"] = os.environ["TEMP"] = os.environ["TMP"] = tmp
    tempfile.tempdir = tmp
    import harness                           # after the temp dir is private
    from exactdoc import convert
    from exactdoc.errors import ExactdocError, OracleDegradedWarning
    stem = os.path.splitext(doc_id)[0]
    work = os.path.join(out_root, stem)
    os.makedirs(work, exist_ok=True)
    docx = os.path.join(work, stem + ".docx")
    row = {"document": doc_id, "tier": tier, "dialect": dialect}
    t0 = time.time()
    try:
        # Escalated: a conversion whose oracle failed mid-run is published
        # open-loop with a warning, and measuring it would report the raw
        # profile under the product's name. Recorded as an error instead.
        with warnings.catch_warnings():
            warnings.simplefilter("error", OracleDegradedWarning)
            convert(path, docx, options=_profile(profile_name), max_pages=0)
    except ExactdocError as e:
        row["refused"] = type(e).__name__
        row["detail"] = str(e)[:200]
        return row
    except Exception as e:                   # a crash is a finding, not a skip
        row["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
        return row
    row["convert_s"] = round(time.time() - t0, 1)
    try:
        res = harness.evaluate(path, docx, work, save_images=save_images)
    except Exception as e:
        row["error"] = "evaluate %s: %s" % (type(e).__name__, str(e)[:300])
        return row
    if "error" in res:
        row["error"] = res["error"]
        return row
    for k in KEYS:
        if k in res:
            row[k] = res[k]
    row["page_ratio"] = round(res["out_pages"] / max(1, res["src_pages"]), 3)
    row["docx_bytes"] = res.get("docx_bytes")
    try:
        row["char_recall"], row["char_doc_recall"] = char_recall(path, res["render_pdf"])
    except Exception as e:
        row["char_recall_error"] = "%s: %s" % (type(e).__name__, str(e)[:200])
    try:
        row["editability"] = editability(docx, res["src_pages"])
        row["edit_score"] = row["editability"]["edit_score"]
    except Exception as e:                   # a census failure is not a conversion failure
        row["editability_error"] = "%s: %s" % (type(e).__name__, str(e)[:200])
    worst = sorted((res.get("page_dy_p90") or {}).items(),
                   key=lambda kv: -kv[1])[:5]
    row["worst_pages_dy90"] = worst
    return row


def summarise(rows):
    ok = [r for r in rows if "page_ratio" in r]
    s = {"documents": len(rows), "measured": len(ok),
         "refused": sum(1 for r in rows if "refused" in r),
         "errors": sum(1 for r in rows if "error" in r)}
    if ok:
        s["page_exact"] = sum(1 for r in ok if r["src_pages"] == r["out_pages"])
        s["median_ratio"] = round(statistics.median(r["page_ratio"] for r in ok), 3)
        s["mean_abs_ratio_err"] = round(statistics.mean(
            abs(r["page_ratio"] - 1) for r in ok), 4)
        for k in ("word_recall", "doc_recall", "char_recall", "char_doc_recall",
                  "within2pt", "live_text_cov", "mean_ssim", "edit_score"):
            vals = [r[k] for r in ok if k in r]
            if vals:
                s["mean_" + k.replace("mean_", "")] = round(statistics.mean(vals), 4)
        s["total_convert_s"] = round(sum(r.get("convert_s", 0) for r in ok), 1)
    return s


def table(rows, prev=None):
    prev = {r["document"]: r for r in (prev or [])}
    lines = ["%-30s %5s %5s %6s %6s %6s %6s %6s %6s %6s %6s %6s" % (
        "document", "src", "out", "ratio", "recall", "docrec", "<2pt",
        "dy50", "dy90", "ssim", "edit", "sec")]
    for r in rows:
        name = r["document"][:30]
        if "refused" in r:
            lines.append("%-30s refused: %s" % (name, r["refused"]))
            continue
        if "error" in r:
            lines.append("%-30s ERROR: %s" % (name, r["error"][:90]))
            continue
        lines.append("%-30s %5d %5d %6.3f %6.3f %6.3f %6.3f %6.2f %6.1f %6.3f %6.3f %6.1f" % (
            name, r["src_pages"], r["out_pages"], r["page_ratio"],
            r.get("word_recall", 0), r.get("doc_recall", 0),
            r.get("within2pt", 0), r.get("dy_p50", -1), r.get("dy_p90", -1),
            r.get("mean_ssim", 0), r.get("edit_score", -1), r.get("convert_s", 0)))
        p = prev.get(r["document"])
        if p and "page_ratio" in p:
            d = lambda k: r.get(k, 0) - p.get(k, 0)
            lines.append("%-30s %5s %+5d %+6.3f %+6.3f %+6.3f %+6.3f %+6.2f %+6.1f %+6.3f %+6.3f" % (
                "  delta", "", r["out_pages"] - p["out_pages"], d("page_ratio"),
                d("word_recall"), d("doc_recall"), d("within2pt"),
                d("dy_p50"), d("dy_p90"), d("mean_ssim"), d("edit_score")))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", choices=("gated", "expansion", "both"),
                    default="expansion")
    ap.add_argument("--profile", choices=("product", "raw", "gdocs"),
                    default="product")
    ap.add_argument("--only", nargs="+", default=None,
                    help="substrings; measure only the matching documents")
    ap.add_argument("--include-unsupported", action="store_true",
                    help="also run the documents the converter must refuse")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--json", default=None, help="write the payload here")
    ap.add_argument("--compare", default=None,
                    help="a previous payload; print per-document deltas")
    ap.add_argument("--images", action="store_true",
                    help="keep side-by-side page images (slow, large)")
    a = ap.parse_args(argv)

    docs = select(a.corpus, a.only, a.include_unsupported)
    if not docs:
        print("no documents selected")
        return 1
    out_root = os.path.join(a.out, a.profile)
    os.makedirs(os.path.join(out_root, "_tmp"), exist_ok=True)
    prof = _profile(a.profile)
    print("QUALITY SWEEP -- NON-GATING MEASUREMENT")
    print("profile   %s" % prof.profile_id())
    print("documents %d, jobs %d" % (len(docs), a.jobs))
    t0 = time.time()
    rows = []
    jobs = [(d, p, t, dl, a.profile, out_root, a.images) for d, p, t, dl in docs]
    with ProcessPoolExecutor(max_workers=a.jobs) as ex:
        futs = {ex.submit(_work, j): j[0] for j in jobs}
        for f in as_completed(futs):
            try:
                r = f.result()
            except Exception as e:           # worker died (OOM, segfault)
                r = {"document": futs[f], "error": "worker: %r" % (e,)}
            rows.append(r)
            print("  done %-30s %s" % (r["document"][:30],
                  r.get("refused") or r.get("error", "")[:60] or
                  "%s/%s pages" % (r.get("src_pages"), r.get("out_pages"))),
                  flush=True)
    rows.sort(key=lambda r: r["document"])
    prev = None
    if a.compare:
        with open(a.compare, encoding="utf-8") as f:
            prev = json.load(f)["documents"]
    print()
    print(table(rows, prev))
    summ = summarise(rows)
    print()
    print(json.dumps(summ, indent=1))
    if prev:
        print("previous: " + json.dumps(summarise(prev)))
    # `jobs` is recorded because convert_s depends on it: documents converted
    # side by side with LibreOffice evaluations took 1.4-2.3x their one-at-a-
    # time wall time (y13 product 147s in a sweep, 76s alone; WP20b,
    # docs/evidence/refine-speed-2026-10-05.json), and the beta bar's speed
    # criterion reads this field to say so.
    # `reading` is the harness reading every word metric here was scored in
    # (harness.reading(): HARNESS_READING and a hash of the reading code), so
    # beta_readiness can refuse to compare two sweeps read differently
    # (amendment 4 (a)). Imported only now: the workers are done, and the
    # harness's LibreOffice profile is never touched by asking its reading.
    import harness
    payload = {"schema": SCHEMA, "gating": False, "adjudicated": False,
               "profile": prof.profile_id(), "corpus": a.corpus,
               "reading": harness.reading(),
               "jobs": a.jobs,
               "elapsed_s": round(time.time() - t0, 1),
               "summary": summ, "documents": rows}
    if a.json:
        tmp = a.json + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=1, sort_keys=True)
        os.replace(tmp, a.json)
    return 0 if not summ["errors"] else 2


if __name__ == "__main__":
    sys.exit(main())
