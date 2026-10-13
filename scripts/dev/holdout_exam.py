"""A release exam: R1-R5 on a sealed holdout set (beta-bar.md, amendment 6).

    python scripts/dev/holdout_exam.py resolve [--exam holdout3] [--hold DIR] [--locate]
    python scripts/dev/holdout_exam.py verdict --exam holdout3 --manifest M \\
        --product P.sweep.json --word ROWS.jsonl [--raw R.sweep.json] \\
        [--cli-exits CLI.json] [--docs ROWS.jsonl] [--commit C] \\
        --json OUT.json --text OUT.txt
    python scripts/dev/holdout_exam.py verify-manifest M --exam holdout3 [--pdfs DIR] \\
        [--expect-promised N]
    python scripts/dev/holdout_exam.py guard --ledger L --evidence-dir D --run NAME \\
        --commit C [--rerun-reason TEXT] [--record]
    python scripts/dev/holdout_exam.py finish --ledger L --run NAME --commit C --evidence E
    python scripts/dev/holdout_exam.py wrap OUT.json --exam EXAM.json --text EXAM.txt \\
        --commit C --input label=path ... [--rerun-reason TEXT]

**Which exam** is one row of `EXAMS`: the release it decides, the sealed
manifest's SHA-256 and document count, the set's directory and manifest name,
the promise field, and the ledger, state suffix and evidence prefix that keep
one exam's single use apart from another's. Holdout-3 (0.3.0b2, the default)
reads its SHA-256 and count from its registration,
`docs/evidence/holdout3-registration-2026-10-12.json`, committed before the
set was opened; holdout-2 (0.3.0b1, run 2026-10-11) stays selectable for
history. `resolve` prints the row for the shell runner.

`verdict` is a pure reading of rows already measured; it converts nothing. Its
exit status: 0 = R1-R3 pass ("announce: yes"), 1 = a gating criterion failed
("announce: no"), 3 = the inputs are not a valid exam (wrong manifest, wrong
profile, another commit, a lane that did not finish) and no verdict is given.

**What is promised** is the manifest's own classification, written down before
anything was converted: the first of the exam's promise fields that every
document carries as a boolean (holdout-2: `promised_b_narrowed`, the narrowed
promise of amendment 6 point 2; holdout-3: `promised_narrowed`, the field its
sealed manifest carries, 35 of 41 true). A field some documents lack is
refused, never mixed; a missing field is refused with the names of the
boolean fields that are there. R2's and R3's
denominators are that exam's own promised documents. A document is short when
the manifest's page count is <= 20, long when it is > 20.

**The criteria, as amendment 6 states them, and how each is read here** (the
reading is fixed in this file before the exam runs, and printed with it):

R1 (gating) -- 0 crashes; every refusal has its typed exit code; Word opens
    100% without a repair prompt.
    * a crash is a product-sweep row with `error` (conversion, scoring or worker);
      the raw sweep's crashes are reported beside it, not gated (the release is
      the product profile);
    * a refusal is typed when its exception class's `code` maps to an exit code
      in `exactdoc.cli.EXIT_CODES` other than 1 (1 = "an unclassified failure");
      when the runner's CLI confirmation is supplied (`--cli-exits`), the exit
      status the real CLI returned must also equal that code;
    * every document the product sweep wrote a DOCX for must have a Word row
      with `opened` true, no `repair_prompt` and no `hang`.
R2 (gating) -- short promised: page-exact on >= 80% in LibreOffice AND in Word;
    word recall >= 0.9 on >= 80%. The word-recall share is required in EACH lane
    (LibreOffice and Word), the stricter reading of a sentence that names both
    lanes. The denominator is every short promised document in the manifest: a
    refused, crashed or unmeasured one counts as a miss.
R3 (gating) -- promised catastrophic (char recall < 0.5, or pages off by more
    than 20%: |out/src - 1| > 0.20): 0 short, <= 1 long. Char recall is the
    right-page `char_recall` (as holdout-1 read it). A document is catastrophic
    when it is in EITHER lane; a promised document with no output in a lane
    (refused, crashed, unmeasured) is catastrophic in that lane.
R4 (reported) -- long promised: median |delta pages| %, the share within
    max(1, 2% of the source's pages), the share with word recall >= 0.85; per
    lane, LibreOffice first (the README number). Shares are over every long
    promised document; the median is over the measured ones.
R5 (reported) -- Google Docs: short promised documents, from `--docs` rows when
    a live Docs lane was flown; the gated-16
    live qualification stays, and is not read here.

"announce: yes" iff R1, R2 and R3 pass.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import statistics
import sys

SCHEMA = "exactdoc.holdout-exam.v1"
EVIDENCE_SCHEMA = "exactdoc.holdout-exam-evidence.v1"
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(os.path.dirname(HERE))
# holdout-2's sealed manifest (docs/beta-bar.md, "Holdout-2 sealed"), run once on
# 2026-10-11 for 0.3.0b1 and published as docs/evidence/holdout2-manifest.json
SEALED_SHA256 = "4db48b08935795065af12016dd3c975eb37860e6299d101554cf61fde3460d61"
PROMISE_FIELD = "promised_b_narrowed"
# One row per sealed set. Everything that ties a run to its set is here, so two
# exams never share a ledger, a state directory, an evidence name or a hash.
EXAMS = {
    "holdout2": {"release": "0.3.0b1", "sha256": SEALED_SHA256, "documents": 32,
                 "set_dir": r"C:\lotmp\rv_hold2", "manifest": "holdout2.json",
                 "promise_fields": ("promised_b_narrowed",),
                 "ledger": "holdout2-exam.ledger.jsonl", "state_suffix": ".holdout2",
                 "prefix": "holdout2-", "tag": "h2", "r3_rule": "v1"},
    "holdout3": {"release": "0.3.0b2",
                 "registration": "docs/evidence/holdout3-registration-2026-10-12.json",
                 "set_dir": r"C:\lotmp\rv_hold3", "manifest": "holdout3.json",
                 # the field holdout-3's sealed manifest carries (named by the
                 # harness's own refusal on 2026-10-13, before any start was
                 # recorded: "promised_narrowed (35 true)")
                 "promise_fields": ("promised_narrowed",),
                 "ledger": "holdout3-exam.ledger.jsonl", "state_suffix": ".holdout3",
                 "prefix": "holdout3-", "tag": "h3", "r3_rule": "v1"},
    # 0.3.0b3's exam (beta-bar.md, amendment 7). Placeholders until holdout-4 is
    # collected, sealed and registered by an agent independent of the fixes: the
    # SHA-256, the document count and (if it names one) the promise field come
    # from docs/evidence/holdout4-registration-<date>.json, and until exactly one
    # such file exists every use of this row is refused as "not registered".
    "holdout4": {"release": "0.3.0b3",
                 "registration": "docs/evidence/holdout4-registration-*.json",
                 "set_dir": r"C:\lotmp\rv_hold4", "manifest": "holdout4.json",
                 "promise_fields": ("promised_narrowed",),
                 "ledger": "holdout4-exam.ledger.jsonl", "state_suffix": ".holdout4",
                 "prefix": "holdout4-", "tag": "h4", "r3_rule": "v2"},
}
DEFAULT_EXAM = "holdout3"
SHORT_MAX_PAGES = 20          # amendment 6: short = <= 20 pages
SHARE_NEEDED = (80, 100)      # >= 80%, compared in integers (no float edge)
WR_SHORT = 0.9                # R2 word recall
CAT_CHAR = 0.5                # R3 v1: char recall below this is catastrophic
CAT_PAGES = 0.20              # R3 v1: |out/src - 1| above this; v2: |dpages| > max(1, 20%)
CAT_DOC_RECALL = 0.9          # R3 v2: document-level word recall (doc_recall) below this
CAT_PAGES_MIN = 1             # R3 v2: the page allowance is never under one page
# R3, as each exam reads it. v1 is amendment 6's, the rule holdout-2 and
# holdout-3 were run under; v2 is amendment 7's (owner-adopted 2026-10-13), for
# holdout-4 on. A recorded verdict is never re-read under another rule.
R3_RULES = {
    "v1": "R3 v1 (amendment 6): a promised document is catastrophic if, in either lane, it "
          "is refused, crashes or has no output, or its right-page char recall is < 0.5, or "
          "|out/src - 1| > 0.20.",
    "v2": "R3 v2 (amendment 7): a promised document is catastrophic if, in either lane: (a) it "
          "is refused, crashes or has no output; (b) document-level word recall (words found "
          "anywhere in the output, doc_recall) < 0.9; or (c) |dpages| > max(1, 20% of the "
          "source pages). Right-page recall and drift inside (c) belong to R2 and are reported "
          "per document.",
}
CAT_LONG_ALLOWED = 1          # R3: <= 1 long promised catastrophic
WR_LONG = 0.85                # R4 word recall
LONG_WITHIN_FRAC = 0.02       # R4 within max(1, 2%)
NO_DOCX = "no DOCX in the supplied tree"
INTERPRETATION = (
    "R2: the word-recall share is required in each lane (LibreOffice and Word); "
    "refused/crashed/unmeasured short promised documents count as misses. "
    "R3: catastrophic in either lane counts; no output in a lane is catastrophic; "
    "char recall = right-page char_recall. R1: crashes are product-sweep rows; raw "
    "is reported; a refusal is typed when its code maps to an exit code other "
    "than 1, and the real CLI's exit status must equal it when confirmed.")
INTERPRETATION_V2 = (
    "R2: the word-recall share is required in each lane (LibreOffice and Word); "
    "refused/crashed/unmeasured short promised documents count as misses. "
    "R3 (v2): catastrophic in either lane counts; no output in a lane is catastrophic; "
    "word recall = document-level doc_recall; pages = |dpages| > max(1, 20%). R1: crashes "
    "are product-sweep rows; raw is reported; a refusal is typed when its code maps to an "
    "exit code other than 1, and the real CLI's exit status must equal it when confirmed.")


class ExamInvalid(Exception):
    """The inputs are not a valid exam: no verdict is given."""


# ------------------------------------------------------------------- reading
def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def exam(name=DEFAULT_EXAM, root=PROJECT):
    """The EXAMS row `name`, with a registered set's SHA-256 and count filled in
    from its registration file (refused when it cannot be read)."""
    if name not in EXAMS:
        raise ExamInvalid("unknown exam %r (known: %s)" % (name, ", ".join(sorted(EXAMS))))
    row = dict(EXAMS[name], name=name)
    if row.get("registration"):
        path = os.path.join(root, row["registration"])
        if "*" in path:
            import glob
            hits = sorted(glob.glob(path))
            if not hits:
                raise ExamInvalid("%s is not registered: no %s (a sealed set is registered "
                                  "before it is run)" % (name, row["registration"]))
            if len(hits) > 1:
                raise ExamInvalid("%s: %d registrations match %s; there must be one"
                                  % (name, len(hits), row["registration"]))
            path = hits[0]
            row["registration"] = os.path.relpath(path, root).replace(os.sep, "/")
        try:
            with open(path, encoding="utf-8") as fh:
                reg = json.load(fh)
        except (OSError, ValueError) as e:
            raise ExamInvalid("%s: the registration cannot be read: %s" % (name, e))
        sha, n = reg.get("manifest_sha256"), reg.get("documents")
        if not (isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha)) \
                or not isinstance(n, int) or n < 1:
            raise ExamInvalid("%s: the registration names no SHA-256 or document count" % name)
        row["sha256"], row["documents"] = sha, n
        if isinstance(reg.get("promise_field"), str) and reg["promise_field"]:
            row["promise_fields"] = (reg["promise_field"],)
    return row


def locate_manifest(set_dir, name, sha):
    """set_dir/name if it exists, else the one *.json in set_dir with the sealed
    SHA-256 (the hash, not the name, identifies the sealed manifest)."""
    path = os.path.join(set_dir, name)
    if os.path.isfile(path):
        return path
    hits = []
    if os.path.isdir(set_dir):
        hits = [os.path.join(set_dir, f) for f in sorted(os.listdir(set_dir))
                if f.lower().endswith(".json") and sha256(os.path.join(set_dir, f)) == sha]
    if len(hits) != 1:
        raise ExamInvalid("%s: no %s, and %d *.json there with the sealed SHA-256 %s"
                          % (set_dir, name, len(hits), sha))
    return hits[0]


def load_manifest(path, expected_sha256, promise_fields=(PROMISE_FIELD,), documents=None):
    """(manifest, {file name: spec}). Refuses another manifest, another document
    count, or a promise no field carries for every document. Each spec gets
    `_promised` (bool) and `_promise_field`, the field it was read from."""
    if isinstance(promise_fields, str):
        promise_fields = (promise_fields,)
    got = sha256(path)
    if not expected_sha256:
        raise ExamInvalid("no sealed SHA-256 to check the manifest against")
    if got != expected_sha256.lower():
        raise ExamInvalid("manifest SHA-256 %s is not the sealed %s" % (got, expected_sha256))
    with open(path, encoding="utf-8") as fh:
        man = json.load(fh)
    specs = man.get("documents") or {}
    if not specs:
        raise ExamInvalid("the manifest lists no documents")
    if documents is not None and len(specs) != documents:
        raise ExamInvalid("the manifest lists %d documents, the registration %d"
                          % (len(specs), documents))
    field = None
    for f in promise_fields:
        have = [isinstance(s.get(f), bool) for s in specs.values()]
        if all(have):
            field = f
            break
        if any(have):
            raise ExamInvalid("the promise field %r is a boolean on %d of %d documents only"
                              % (f, sum(have), len(have)))
    if field is None:
        # Name what IS there (field names and how many documents are true under
        # each, never a document's own classification), so the exam's row can be
        # corrected without anyone opening the sealed manifest.
        keys = sorted(set.intersection(*(set(s) for s in specs.values())))
        common = [k for k in keys if all(isinstance(s[k], bool) for s in specs.values())]
        raise ExamInvalid("no document carries a boolean promise field (looked for %s); "
                          "boolean fields on every document: %s; every document's fields: %s"
                          % (", ".join(promise_fields),
                             ", ".join("%s (%d true)" % (k, sum(s[k] for s in specs.values()))
                                       for k in common) or "none", ", ".join(keys)))
    docs = {}
    for key, spec in specs.items():
        name = spec.get("file") or key
        if not isinstance(spec.get("pages"), int) or spec["pages"] < 1:
            raise ExamInvalid("%s: the manifest has no page count" % key)
        docs[name] = dict(spec, _key=key, _promised=spec[field], _promise_field=field)
    return man, docs


def load_sweep(path):
    if not path:
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_jsonl(path, key="doc"):
    """{doc: row}; a later row for the same document supersedes an earlier one."""
    if not path or not os.path.exists(path):
        return None
    out = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                r = json.loads(line)
                if r.get(key):
                    out[r[key]] = r
    return out


def exit_map_from_tree():
    """{exception class name: (code, exit status)} from the measured tree's exactdoc."""
    from exactdoc import errors
    from exactdoc.cli import EXIT_CODES
    out = {}
    for name in dir(errors):
        cls = getattr(errors, name)
        if isinstance(cls, type) and issubclass(cls, errors.ExactdocError):
            out[name] = (cls.code, EXIT_CODES.get(cls.code, 1))
    return out


def shipped_profiles():
    """(product profile id, raw profile id) of the measured tree, or (None, None)."""
    try:
        from exactdoc.options import PRODUCT, RAW
    except Exception:
        return None, None
    return PRODUCT.profile_id(), RAW.profile_id()


# ------------------------------------------------------------------ the lanes
def _share_ok(count, n):
    return n > 0 and count * SHARE_NEEDED[1] >= SHARE_NEEDED[0] * n


def _pct(count, n):
    return round(100.0 * count / n, 1) if n else None


def _r3_reasons(lane, rule="v1"):
    """Why a lane is catastrophic under R3 `rule` ([] when it is not)."""
    if lane["status"] != "measured":
        return ["no output (%s)" % (lane.get("refused") or lane["status"])]
    why = []
    if rule == "v2":
        dr = lane.get("doc_recall")
        if dr is None or dr < CAT_DOC_RECALL:
            why.append("doc_recall %s < %.1f" % ("missing" if dr is None else "%.3f" % dr,
                                                  CAT_DOC_RECALL))
        allow = max(CAT_PAGES_MIN, CAT_PAGES * lane["src_pages"])
        if abs(lane["delta_pages"]) > allow:
            why.append("|dpages| %d > %s" % (abs(lane["delta_pages"]), ("%g" % allow)))
        return why
    cr = lane.get("char_recall")
    if cr is not None and cr < CAT_CHAR:
        why.append("char_recall %.3f < %.1f" % (cr, CAT_CHAR))
    if abs(lane["out_pages"] / lane["src_pages"] - 1) > CAT_PAGES:
        why.append("pages %d/%d off by more than 20%%" % (lane["out_pages"], lane["src_pages"]))
    return why


def _catastrophic(lane, rule="v1"):
    """True / False for a measured lane, True for no output (see R3)."""
    return bool(_r3_reasons(lane, rule))


def _lane_from_sweep(row, pages):
    if row is None:
        return {"status": "missing"}
    if "refused" in row:
        return {"status": "refused", "refused": row["refused"]}
    if "error" in row:
        return {"status": "error", "error": str(row["error"])[:200]}
    if not row.get("out_pages"):
        return {"status": "error", "error": "unmeasured: no out_pages"}
    src = row.get("src_pages") or pages
    return _measured(src, row)


def _measured(src, row):
    out = row["out_pages"]
    lane = {"status": "measured", "src_pages": src, "out_pages": out,
            "word_recall": row.get("word_recall"), "char_recall": row.get("char_recall"),
            "doc_recall": row.get("doc_recall"),
            "exact": out == src,
            "delta_pages": out - src,
            "delta_pct": round(100.0 * abs(out - src) / src, 2)}
    lane["catastrophic"] = _catastrophic(lane)
    return lane


def _lane_from_word(row, pages):
    if row is None:
        return {"status": "missing"}
    base = {"opened": bool(row.get("opened")), "repair_prompt": bool(row.get("repair_prompt")),
            "hang": bool(row.get("hang"))}
    if "error" in row:
        status = "no-docx" if NO_DOCX in str(row["error"]) else "error"
        return dict(base, status=status, error=str(row["error"])[:200])
    if not row.get("out_pages"):
        return dict(base, status="error", error="unmeasured: no out_pages")
    lane = _measured(row.get("src_pages") or pages, row)
    lane.update(base)
    return lane


def _r_short(docs, lane, wr_min):
    n = len(docs)
    exact = [d["doc"] for d in docs if d[lane]["status"] == "measured" and d[lane]["exact"]]
    wr = [d["doc"] for d in docs if d[lane]["status"] == "measured"
          and (d[lane].get("word_recall") or 0) >= wr_min]
    return {"n": n, "page_exact": len(exact), "page_exact_pct": _pct(len(exact), n),
            "page_exact_ok": _share_ok(len(exact), n),
            "wr_ok_count": len(wr), "wr_ok_pct": _pct(len(wr), n),
            "wr_ok": _share_ok(len(wr), n),
            "misses_pages": [d["doc"] for d in docs if d["doc"] not in exact],
            "misses_wr": [d["doc"] for d in docs if d["doc"] not in wr]}


def _r_long(docs, lane):
    n = len(docs)
    meas = [d[lane] for d in docs if d[lane]["status"] == "measured"]
    within = [m for m in meas
              if abs(m["delta_pages"]) <= max(1.0, LONG_WITHIN_FRAC * m["src_pages"])]
    wr = [m for m in meas if (m.get("word_recall") or 0) >= WR_LONG]
    return {"n": n, "measured": len(meas),
            "median_abs_delta_pages_pct": round(statistics.median(m["delta_pct"] for m in meas), 2)
            if meas else None,
            "within_max1_2pct": len(within), "within_max1_2pct_share": _pct(len(within), n),
            "wr_ge_085": len(wr), "wr_ge_085_share": _pct(len(wr), n)}


# -------------------------------------------------------------------- verdict
def evaluate(man_docs, product, word_rows, raw=None, cli_exits=None, docs_rows=None,
             exit_map=None, expect_commit=None, profiles=(None, None), manifest_meta=None,
             exam_name=None, r3_rule="v1"):
    """The exam. Raises ExamInvalid when the inputs cannot carry a verdict.

    `man_docs` is load_manifest's {file: spec}: each spec's `_promised` is the
    exam's own classification (a spec without it is read from PROMISE_FIELD)."""
    invalid = []
    prod_id, raw_id = profiles
    if product is None:
        raise ExamInvalid("no product sweep")
    if word_rows is None:
        raise ExamInvalid("no Word rows")

    def check_sweep(sw, label, want_profile, fatal):
        problems = []
        if want_profile and sw.get("profile") != want_profile:
            problems.append("%s sweep profile %r is not %r" % (label, sw.get("profile"), want_profile))
        prov = sw.get("provenance") or {}
        if expect_commit and prov.get("git_commit") != expect_commit:
            problems.append("%s sweep was made from commit %r, not %s"
                            % (label, prov.get("git_commit"), expect_commit))
        if prov.get("git_dirty") not in (False, 0, "0", None):
            problems.append("%s sweep was made from a dirty tree" % label)
        names = {r.get("document") for r in sw.get("documents", ())}
        missing, extra = sorted(set(man_docs) - names), sorted(names - set(man_docs))
        if missing:
            problems.append("%s sweep lacks %d manifest document(s): %s"
                            % (label, len(missing), " ".join(missing[:8])))
        if extra:
            problems.append("%s sweep has %d document(s) not in the manifest: %s"
                            % (label, len(extra), " ".join(extra[:8])))
        (invalid if fatal else warnings).extend(problems)

    warnings = []
    check_sweep(product, "product", prod_id, True)
    if raw is not None:
        check_sweep(raw, "raw", raw_id, False)
    extra_w = sorted(set(word_rows) - set(man_docs))
    if extra_w:
        invalid.append("Word rows for documents not in the manifest: %s" % " ".join(extra_w[:8]))
    flav = sorted({r.get("flavour") for r in word_rows.values()} - {"product"})
    if flav:
        invalid.append("Word rows of another DOCX flavour: %s" % flav)
    absent_w = sorted(set(man_docs) - set(word_rows))
    if absent_w:
        invalid.append("the Word lane did not finish: no row for %s" % " ".join(absent_w[:8]))
    if r3_rule not in R3_RULES:
        invalid.append("unknown R3 rule %r" % r3_rule)
    if r3_rule == "v2":
        # R3 v2 reads document-level word recall: a measured row without it is an
        # incomplete measurement, never a silent catastrophe or a silent pass
        for label, rows, key in (("product sweep", product.get("documents", ()), "document"),
                                 ("Word", word_rows.values(), "doc")):
            lack = sorted(r.get(key) for r in rows if r.get(key) in man_docs
                          and r.get("out_pages") and "error" not in r and "refused" not in r
                          and not isinstance(r.get("doc_recall"), (int, float)))
            if lack:
                invalid.append("R3 v2 needs doc_recall: %s rows lack it: %s"
                               % (label, " ".join(lack[:8])))
    if invalid:
        raise ExamInvalid("; ".join(invalid))

    p_rows = {r["document"]: r for r in product.get("documents", ())}
    r_rows = {r["document"]: r for r in raw.get("documents", ())} if raw else {}
    if exit_map is None:
        exit_map = exit_map_from_tree()

    docs = []
    for name in sorted(man_docs):
        spec = man_docs[name]
        pages = spec["pages"]
        d = {"doc": name, "design_class": spec.get("design_class"),
             "promised": spec["_promised"] if "_promised" in spec else spec[PROMISE_FIELD],
             "pages": pages,
             "length": "short" if pages <= SHORT_MAX_PAGES else "long",
             "lo": _lane_from_sweep(p_rows.get(name), pages),
             "word": _lane_from_word(word_rows.get(name), pages)}
        if raw is not None:
            d["raw"] = _lane_from_sweep(r_rows.get(name), pages)
        if docs_rows is not None:
            g = docs_rows.get(name)
            d["gdocs"] = {"status": "missing"} if g is None else (
                {"status": "error", "error": str(g["error"])[:200]} if "error" in g
                else (_measured(g.get("src_pages") or pages, g) if g.get("out_pages")
                      else {"status": "error", "error": "unmeasured"}))
        for lane in ("lo", "word"):
            m = d[lane]
            if m["status"] == "measured" and m["src_pages"] != pages:
                warnings.append("%s: %s counts %d source pages, the manifest %d"
                                % (name, lane, m["src_pages"], pages))
        docs.append(d)

    # R1 -----------------------------------------------------------------
    crashes = [{"doc": d["doc"], "error": d["lo"]["error"]} for d in docs
               if d["lo"]["status"] == "error"]
    refusals = []
    for d in docs:
        if d["lo"]["status"] != "refused":
            continue
        cls = d["lo"]["refused"]
        code, typed_exit = exit_map.get(cls, (None, 1))
        rec = {"doc": d["doc"], "refused": cls, "code": code, "typed_exit": typed_exit,
               "typed": typed_exit not in (None, 1)}
        if cli_exits is not None:
            c = cli_exits.get(d["doc"])
            rec["cli_exit"] = None if c is None else c.get("exit")
            rec["typed"] = rec["typed"] and rec["cli_exit"] == typed_exit
        refusals.append(rec)
    untyped = [r for r in refusals if not r["typed"]]
    word_fail = []
    for d in docs:
        w, lo = d["word"], d["lo"]
        if lo["status"] == "refused":
            continue                       # no DOCX to open; R1's refusal check covers it
        if lo["status"] == "error" and w["status"] == "no-docx":
            continue                       # counted as a crash already
        if w["status"] == "no-docx" or not w["opened"] or w["repair_prompt"] or w["hang"]:
            word_fail.append({"doc": d["doc"], "status": w["status"], "opened": w["opened"],
                              "repair_prompt": w["repair_prompt"], "hang": w["hang"],
                              "error": w.get("error")})
    word_errors = [{"doc": d["doc"], "error": d["word"].get("error")} for d in docs
                   if d["word"]["status"] == "error" and d["word"]["opened"]
                   and not d["word"]["repair_prompt"] and not d["word"]["hang"]]
    word_expected = sum(1 for d in docs if d["lo"]["status"] != "refused"
                        and not (d["lo"]["status"] == "error" and d["word"]["status"] == "no-docx"))
    r1 = {"kind": "gating", "crashes": crashes, "refusals": refusals,
          "untyped_refusals": untyped, "word_open_failures": word_fail,
          "word_expected": word_expected, "word_opened_clean": word_expected - len(word_fail),
          "word_scoring_errors": word_errors,
          "cli_confirmed": cli_exits is not None,
          "raw_crashes_reported": [d["doc"] for d in docs if d.get("raw", {}).get("status") == "error"]}
    r1["pass"] = not crashes and not untyped and not word_fail

    # R2 -----------------------------------------------------------------
    short = [d for d in docs if d["promised"] and d["length"] == "short"]
    long_ = [d for d in docs if d["promised"] and d["length"] == "long"]
    r2 = {"kind": "gating", "n": len(short), "lo": _r_short(short, "lo", WR_SHORT),
          "word": _r_short(short, "word", WR_SHORT)}
    r2["pass"] = all(r2[l][k] for l in ("lo", "word") for k in ("page_exact_ok", "wr_ok"))

    # R3 -----------------------------------------------------------------
    for d in docs:
        d["r3_why"] = {lane: _r3_reasons(d[lane], r3_rule) for lane in ("lo", "word")}
        d["catastrophic"] = {lane: bool(d["r3_why"][lane]) for lane in ("lo", "word")}
    cat_s = [d["doc"] for d in short if any(d["catastrophic"].values())]
    cat_l = [d["doc"] for d in long_ if any(d["catastrophic"].values())]
    r3 = {"kind": "gating", "rule": r3_rule, "rule_text": R3_RULES.get(r3_rule),
          "short_catastrophic": cat_s, "long_catastrophic": cat_l,
          "by_lane": {lane: [d["doc"] for d in short + long_ if d["catastrophic"][lane]]
                      for lane in ("lo", "word")},
          "unpromised_catastrophic_reported": [d["doc"] for d in docs if not d["promised"]
                                               and any(d["catastrophic"].values())]}
    r3["pass"] = not cat_s and len(cat_l) <= CAT_LONG_ALLOWED

    # R4 -----------------------------------------------------------------
    r4 ={"kind": "reported", "n": len(long_), "lo": _r_long(long_, "lo"),
          "word": _r_long(long_, "word")}

    # R5 -----------------------------------------------------------------
    if docs_rows is None:
        r5 = {"kind": "reported", "run": False,
              "note": "no live Docs lane was flown for this exam; the gated-16 live "
                      "qualification stays as recorded"}
    else:
        g_short = short
        r5 = {"kind": "reported", "run": True, "n": len(g_short),
              "measured": sum(1 for d in g_short if d["gdocs"]["status"] == "measured"),
              "page_exact": sum(1 for d in g_short if d["gdocs"]["status"] == "measured"
                                and d["gdocs"]["exact"]),
              "wr_ge_09": sum(1 for d in g_short if d["gdocs"]["status"] == "measured"
                              and (d["gdocs"].get("word_recall") or 0) >= WR_SHORT),
              "note": "the gated-16 live qualification stays as recorded"}

    announce = r1["pass"] and r2["pass"] and r3["pass"]
    fields = sorted({s.get("_promise_field") or PROMISE_FIELD for s in man_docs.values()})
    return {"schema": SCHEMA, "valid": True, "announce": announce, "exam": exam_name,
            "synthetic": bool((manifest_meta or {}).get("synthetic")),
            "promise_field": ",".join(fields),
            "interpretation": INTERPRETATION_V2 if r3_rule == "v2" else INTERPRETATION,
            "counts": {"documents": len(docs), "promised": len(short) + len(long_),
                       "short_promised": len(short), "long_promised": len(long_)},
            "R1": r1, "R2": r2, "R3": r3, "R4": r4, "R5": r5,
            "warnings": warnings, "documents": docs}


# ---------------------------------------------------------------------- text
def _f(v, fmt="%.3f"):
    return "-" if v is None else fmt % v


def _cell(lane):
    if lane is None:
        return "%-14s" % "-"
    if lane["status"] != "measured":
        tag = lane.get("refused") or lane["status"]
        return "%-14s" % tag[:14]
    return "%3d/%-3d %s" % (lane["out_pages"], lane["src_pages"], _f(lane.get("word_recall"), "%.2f"))


def render_text(res):
    L = []
    pf = lambda ok: "PASS" if ok else "FAIL"
    if res.get("synthetic"):
        L.append("*** SYNTHETIC DRY RUN: plumbing only, not the %s exam ***"
                 % (res.get("exam") or "holdout"))
    c = res["counts"]
    L.append("%s exam (beta-bar.md amendment 6): %d documents, %d promised "
             "(%d short, %d long) under %s"
             % (res.get("exam") or "holdout", c["documents"], c["promised"],
                c["short_promised"], c["long_promised"], res["promise_field"]))
    r1 = res["R1"]
    L.append("R1 %s  crashes %d; refusals %d (untyped %d%s); Word opened clean %d/%d"
             % (pf(r1["pass"]), len(r1["crashes"]), len(r1["refusals"]),
                len(r1["untyped_refusals"]), ", CLI-confirmed" if r1["cli_confirmed"] else
                ", static mapping only", r1["word_opened_clean"], r1["word_expected"]))
    for x in r1["crashes"]:
        L.append("     crash %s: %s" % (x["doc"], x["error"][:100]))
    for x in r1["refusals"]:
        L.append("     refused %s: %s code=%s typed_exit=%s cli_exit=%s %s"
                 % (x["doc"], x["refused"], x["code"], x["typed_exit"], x.get("cli_exit", "-"),
                    "ok" if x["typed"] else "UNTYPED"))
    for x in r1["word_open_failures"]:
        L.append("     Word %s: status=%s opened=%s repair=%s hang=%s"
                 % (x["doc"], x["status"], x["opened"], x["repair_prompt"], x["hang"]))
    if r1["word_scoring_errors"]:
        L.append("     (Word scoring errors, opened fine: %s)"
                 % " ".join(x["doc"] for x in r1["word_scoring_errors"]))
    if r1["raw_crashes_reported"]:
        L.append("     (raw sweep crashes, reported only: %s)" % " ".join(r1["raw_crashes_reported"]))
    r2 = res["R2"]
    for lane, label in (("lo", "LibreOffice"), ("word", "Word")):
        x = r2[lane]
        L.append("R2 %s  %-11s short promised page-exact %d/%d = %s%% (%s); word recall >= 0.9 "
                 "%d/%d = %s%% (%s)"
                 % (pf(r2["pass"]), label, x["page_exact"], x["n"], _f(x["page_exact_pct"], "%.0f"),
                    "ok" if x["page_exact_ok"] else "below 80%", x["wr_ok_count"], x["n"],
                    _f(x["wr_ok_pct"], "%.0f"), "ok" if x["wr_ok"] else "below 80%"))
    r3 = res["R3"]
    L.append("R3 %s  promised catastrophic (%s): short %d (allowed 0) %s; long %d (allowed %d) %s"
             % (pf(r3["pass"]), r3.get("rule", "v1"), len(r3["short_catastrophic"]),
                " ".join(r3["short_catastrophic"]),
                len(r3["long_catastrophic"]), CAT_LONG_ALLOWED, " ".join(r3["long_catastrophic"])))
    r4 = res["R4"]
    for lane, label in (("lo", "LibreOffice"), ("word", "Word")):
        x = r4[lane]
        L.append("R4 reported %-11s long promised n=%d (measured %d): median |dpages| %s%%; "
                 "within max(1,2%%) %d/%d = %s%%; word recall >= 0.85 %d/%d = %s%%"
                 % (label, x["n"], x["measured"], _f(x["median_abs_delta_pages_pct"], "%.1f"),
                    x["within_max1_2pct"], x["n"], _f(x["within_max1_2pct_share"], "%.0f"),
                    x["wr_ge_085"], x["n"], _f(x["wr_ge_085_share"], "%.0f")))
    r5 = res["R5"]
    if r5["run"]:
        L.append("R5 reported Google Docs short promised: measured %d/%d, page-exact %d, "
                 "word recall >= 0.9 %d; %s" % (r5["measured"], r5["n"], r5["page_exact"],
                                                r5["wr_ge_09"], r5["note"]))
    else:
        L.append("R5 reported: %s" % r5["note"])
    L.append("announce: %s   (R1 %s, R2 %s, R3 %s)"
             % ("yes" if res["announce"] else "no", pf(r1["pass"]), pf(r2["pass"]), pf(r3["pass"])))
    for w in res["warnings"]:
        L.append("warning: %s" % w)
    L.append("reading: %s" % res["interpretation"])
    L.append("")
    has_raw = any("raw" in d for d in res["documents"])
    has_gd = any("gdocs" in d for d in res["documents"])
    head = "%-44s %-21s %-1s %4s %-5s | %-14s %-5s | %-14s %-5s %-4s" % (
        "document", "class", "P", "pp", "len", "LO pages  wr", "cr", "Word pages wr", "cr", "open")
    if has_raw:
        head += " | %-14s" % "raw pages wr"
    if has_gd:
        head += " | %-14s" % "Docs pages wr"
    L.append(head + " | flags")
    for d in res["documents"]:
        lo, w = d["lo"], d["word"]
        opened = "-" if w["status"] in ("missing", "no-docx") and not w.get("opened") else (
            "ok" if w.get("opened") and not w.get("repair_prompt") and not w.get("hang")
            else "FAIL")
        line = "%-44s %-21s %-1s %4d %-5s | %s %-5s | %s %-5s %-4s" % (
            d["doc"][:44], (d["design_class"] or "")[:21], "P" if d["promised"] else "-",
            d["pages"], d["length"], _cell(lo), _f(lo.get("char_recall"), "%.2f"),
            _cell(w), _f(w.get("char_recall"), "%.2f"), opened)
        if has_raw:
            line += " | %s" % _cell(d.get("raw"))
        if has_gd:
            line += " | %s" % _cell(d.get("gdocs"))
        flags = []
        if d["promised"]:
            if d["catastrophic"]["lo"] or d["catastrophic"]["word"]:
                flags.append("CATASTROPHIC(%s)" % ",".join(l for l in ("lo", "word")
                                                          if d["catastrophic"][l]))
            if d["length"] == "short":
                for lane in ("lo", "word"):
                    m = d[lane]
                    if not (m["status"] == "measured" and m["exact"]):
                        flags.append("%s-pages" % lane)
                    if not (m["status"] == "measured" and (m.get("word_recall") or 0) >= WR_SHORT):
                        flags.append("%s-wr" % lane)
        L.append(line + " | " + " ".join(flags))
    return "\n".join(L) + "\n"


# ------------------------------------------------------------- single use
def _ledger(path):
    out = []
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            out = [json.loads(l) for l in fh if l.strip()]
    return out


def _append(path, entry):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    entry = dict(entry, utc=datetime.datetime.now(datetime.timezone.utc)
                 .strftime("%Y-%m-%dT%H:%M:%SZ"))
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def results_pattern(prefix):
    """The names an exam's results file can have: <prefix><date>.json, its
    -rerunN siblings, and the dry run's <prefix>dry-<run>-<date>.json. Nothing
    else with the prefix counts (holdout3-registration-....json is not a result)."""
    return re.compile(r"^%s(dry-.+-)?\d{4}-\d{2}-\d{2}(-rerun\d+)?\.json$" % re.escape(prefix))


def guard(ledger, evidence_dir, run, commit, rerun_reason=None, prefix=None):
    """('fresh'|'resume'|'rerun', [reasons]) or raise ExamInvalid when refused.

    The exam is single-use. Refused: a results file of THIS exam already exists
    in the evidence directory (results_pattern(prefix)); the exam's own ledger
    records a finished exam; or it records a started exam under another run
    name or commit. Resuming the same run on the same commit is not a second
    exam. `rerun_reason` overrides a refusal and is logged. Each exam has its
    own ledger and prefix (EXAMS), so another set's finished exam never blocks
    this one."""
    if not prefix:
        raise ExamInvalid("guard needs the exam's results prefix")
    entries = _ledger(ledger)
    reasons = []
    if evidence_dir and os.path.isdir(evidence_dir):
        pat = results_pattern(prefix)
        found = sorted(f for f in os.listdir(evidence_dir) if pat.match(f))
        if found:
            reasons.append("results already exist: %s" % " ".join(found))
    fin = [e for e in entries if e.get("event") == "finish"]
    if fin:
        reasons.append("the ledger records a finished exam: %s on %s at %s"
                       % (fin[-1].get("run"), fin[-1].get("commit"), fin[-1].get("utc")))
    starts = [e for e in entries if e.get("event") == "start"]
    other = [e for e in starts if (e.get("run"), e.get("commit")) != (run, commit)]
    if other:
        reasons.append("the ledger records another started exam: %s on %s at %s"
                       % (other[-1].get("run"), other[-1].get("commit"), other[-1].get("utc")))
    resume = any((e.get("run"), e.get("commit")) == (run, commit) for e in starts)
    if reasons:
        if not (rerun_reason and rerun_reason.strip()):
            raise ExamInvalid("REFUSED, the exam is single-use: " + "; ".join(reasons)
                              + " (override: --rerun-reason TEXT, which is logged)")
        return "rerun", reasons
    return ("resume" if resume else "fresh"), reasons


# ---------------------------------------------------------------------- CLI
def _cmd_verdict(a):
    if a.tree and a.tree not in sys.path:
        sys.path.insert(0, a.tree)
    try:
        ex = exam(a.exam)
        man, docs = load_manifest(a.manifest, a.manifest_sha256 or ex["sha256"],
                                  ex["promise_fields"],
                                  None if a.manifest_sha256 else ex["documents"])
        product = load_sweep(a.product)
        raw = load_sweep(a.raw) if a.raw else None
        word = load_jsonl(a.word)
        cli = None
        if a.cli_exits:
            with open(a.cli_exits, encoding="utf-8") as fh:
                cli = json.load(fh).get("documents", {})
        gd = load_jsonl(a.docs) if a.docs else None
        if gd is not None:
            gd = {k: v for k, v in gd.items() if not k.startswith("_")}   # the sentinel row
        commit = a.commit or os.environ.get("EXACTDOC_GIT_COMMIT") or None
        res = evaluate(docs, product, word, raw=raw, cli_exits=cli, docs_rows=gd,
                       expect_commit=commit, profiles=shipped_profiles(), manifest_meta=man,
                       exam_name=ex["name"], r3_rule=ex["r3_rule"])
        res["commit"] = commit
        res["manifest_sha256"] = sha256(a.manifest)
        text = render_text(res)
        rc = 0 if res["announce"] else 1
    except ExamInvalid as e:
        res = {"schema": SCHEMA, "valid": False, "announce": False, "invalid": str(e)}
        text = "INVALID EXAM, no verdict: %s\nannounce: no\n" % e
        rc = 3
    if a.json:
        with open(a.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(res, fh, indent=1, ensure_ascii=False, sort_keys=True)
            fh.write("\n")
    if a.text:
        with open(a.text, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    sys.stdout.write(text)
    return rc


def _cmd_verify(a):
    """--sha256 replaces the exam's registered hash and count (the dry run's
    synthetic set); otherwise both come from the exam's row."""
    try:
        ex = exam(a.exam)
        _, docs = load_manifest(a.manifest, a.sha256 or ex["sha256"], ex["promise_fields"],
                                None if a.sha256 else ex["documents"])
    except ExamInvalid as e:
        print("REFUSED: %s" % e)
        return 3
    promised = sum(1 for d in docs.values() if d["_promised"])
    field = next(iter(docs.values()))["_promise_field"]
    if a.expect_promised is not None and promised != a.expect_promised:
        print("REFUSED: %d documents are promised under %s, expected %d"
              % (promised, field, a.expect_promised))
        return 3
    bad = []
    if a.pdfs:
        for name, spec in sorted(docs.items()):
            p = os.path.join(a.pdfs, name)
            if not os.path.exists(p):
                bad.append("%s: missing" % name)
            elif sha256(p) != spec.get("sha256"):
                bad.append("%s: SHA-256 differs from the manifest" % name)
    if bad:
        print("REFUSED: %s" % "; ".join(bad))
        return 3
    print("manifest %s OK (exam %s, SHA-256 %s); %d documents, %d promised under %s%s" % (
        a.manifest, ex["name"], sha256(a.manifest), len(docs), promised, field,
        ", every PDF's SHA-256 matches" if a.pdfs else ""))
    return 0


def rescore_r3(man_docs, product, word_rows, raw=None, cli_exits=None, exit_map=None,
               expect_commit=None, profiles=(None, None), manifest_meta=None, exam_name=None,
               recorded_rule="v1", new_rule="v2"):
    """A recorded exam's R3 re-read under another rule: REPORTED, NOT A VERDICT.

    Both readings come from the same rows (nothing is converted or re-measured);
    the recorded one must reproduce the recorded verdict, which stands."""
    kw = dict(raw=raw, cli_exits=cli_exits, exit_map=exit_map, expect_commit=expect_commit,
              profiles=profiles, manifest_meta=manifest_meta, exam_name=exam_name)
    old = evaluate(man_docs, product, word_rows, r3_rule=recorded_rule, **kw)
    new = evaluate(man_docs, product, word_rows, r3_rule=new_rule, **kw)
    by = {d["doc"]: d for d in new["documents"]}
    rows = []
    for d in old["documents"]:
        if not d["promised"]:
            continue
        n = by[d["doc"]]
        rows.append({"doc": d["doc"], "length": d["length"], "pages": d["pages"],
                     "lanes": {lane: {k: d[lane].get(k) for k in
                                      ("status", "out_pages", "src_pages", "word_recall",
                                       "doc_recall", "char_recall")}
                               for lane in ("lo", "word")},
                     "catastrophic_" + recorded_rule: any(d["catastrophic"].values()),
                     "catastrophic_" + new_rule: any(n["catastrophic"].values()),
                     "why_" + recorded_rule: d["r3_why"], "why_" + new_rule: n["r3_why"]})
    return {"schema": "exactdoc.holdout-r3-rescore.v1",
            "status": "reported, not a verdict",
            "exam": exam_name,
            "recorded_verdict": {"announce": old["announce"], "R1": old["R1"]["pass"],
                                 "R2": old["R2"]["pass"], "R3": old["R3"]["pass"],
                                 "r3_rule": recorded_rule},
            "R3": {rule: {"pass_if_it_were_the_rule": r["R3"]["pass"],
                          "short_catastrophic": r["R3"]["short_catastrophic"],
                          "long_catastrophic": r["R3"]["long_catastrophic"],
                          "rule_text": R3_RULES[rule]}
                   for rule, r in ((recorded_rule, old), (new_rule, new))},
            "R2_unchanged": {"pass": old["R2"]["pass"], "lo": old["R2"]["lo"],
                             "word": old["R2"]["word"]},
            "documents": rows}


def render_rescore(r):
    old_rule, new_rule = r["recorded_verdict"]["r3_rule"], [k for k in r["R3"]
                                                             if k != r["recorded_verdict"]["r3_rule"]][0]
    L = ["*** REPORTED, NOT A VERDICT: %s's R3 re-read under %s ***" % (r["exam"], new_rule),
         "recorded verdict (stands): announce %s (R1 %s, R2 %s, R3 %s under %s)"
         % ("yes" if r["recorded_verdict"]["announce"] else "no",
            *("PASS" if r["recorded_verdict"][k] else "FAIL" for k in ("R1", "R2", "R3")), old_rule)]
    for rule in (old_rule, new_rule):
        x = r["R3"][rule]
        L.append("R3 %s: %s  short %d %s; long %d %s"
                 % (rule, "would pass" if x["pass_if_it_were_the_rule"] else "would fail",
                    len(x["short_catastrophic"]), " ".join(x["short_catastrophic"]),
                    len(x["long_catastrophic"]), " ".join(x["long_catastrophic"])))
    L.append("")
    L.append("%-46s %-5s %-6s | %-24s | %-24s | %-7s %-7s" % (
        "promised document", "len", "pages", "LO out/src doc_rec cr", "Word out/src doc_rec cr",
        old_rule, new_rule))
    for d in r["documents"]:
        cells = []
        for lane in ("lo", "word"):
            x = d["lanes"][lane]
            if x["status"] != "measured":
                cells.append("%-24s" % x["status"])
            else:
                cells.append("%3d/%-3d %5s %5s      " % (
                    x["out_pages"], x["src_pages"],
                    "-" if x["doc_recall"] is None else "%.2f" % x["doc_recall"],
                    "-" if x["char_recall"] is None else "%.2f" % x["char_recall"]))
        flag = lambda b: "CAT" if b else "-"
        L.append("%-46s %-5s %-6d | %s | %s | %-7s %-7s" % (
            d["doc"][:46], d["length"], d["pages"], cells[0], cells[1],
            flag(d["catastrophic_" + old_rule]), flag(d["catastrophic_" + new_rule])))
    return "\n".join(L) + "\n"


def _cmd_rescore(a):
    if a.tree and a.tree not in sys.path:
        sys.path.insert(0, a.tree)
    ex = exam(a.exam)
    man, docs = load_manifest(a.manifest, ex["sha256"], ex["promise_fields"], ex["documents"])
    cli = None
    if a.cli_exits:
        with open(a.cli_exits, encoding="utf-8") as fh:
            cli = json.load(fh).get("documents", {})
    r = rescore_r3(docs, load_sweep(a.product), load_jsonl(a.word),
                   raw=load_sweep(a.raw) if a.raw else None, cli_exits=cli,
                   expect_commit=a.commit, profiles=shipped_profiles(), manifest_meta=man,
                   exam_name=ex["name"], recorded_rule=ex["r3_rule"], new_rule=a.rule)
    r["inputs"] = {k: {"path": v, "sha256": sha256(v)} for k, v in (
        ("manifest", a.manifest), ("product_sweep", a.product), ("word_rows", a.word),
        ("raw_sweep", a.raw), ("cli_exits", a.cli_exits), ("recorded_exam", a.recorded)) if v}
    if a.recorded:
        with open(a.recorded, encoding="utf-8") as fh:
            rec = json.load(fh)
        rec = rec.get("exam", rec)
        same = all(rec.get(k, {}).get("pass") == r["recorded_verdict"][k]
                   for k in ("R1", "R2", "R3")) and rec.get("announce") == r["recorded_verdict"]["announce"]
        r["recorded_verdict_reproduced"] = same
        if not same:
            print("REFUSED: the recorded rule does not reproduce the recorded verdict")
            return 3
    text = render_rescore(r)
    r["text"] = text
    if a.json:
        with open(a.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(r, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
    sys.stdout.write(text)
    return 0


def _cmd_resolve(a):
    """The exam's row as shell assignments (holdout_exam.sh evals them). Only
    --locate looks inside the set directory, to find its manifest."""
    try:
        ex = exam(a.exam)
        hold = a.hold or ex["set_dir"]
        manifest = os.path.join(hold, ex["manifest"])
        if a.locate:
            manifest = locate_manifest(hold, ex["manifest"], ex["sha256"])
    except ExamInvalid as e:
        print("REFUSED: %s" % e, file=sys.stderr)
        return 3
    from shlex import quote
    vals = {"EXAM": ex["name"], "EXAM_RELEASE": ex["release"], "EXAM_SHA": ex["sha256"],
            "EXAM_DOCS": ex["documents"], "EXAM_HOLD": hold,
            "EXAM_MANIFEST": manifest, "EXAM_MANIFEST_NAME": os.path.basename(manifest),
            "EXAM_LEDGER": ex["ledger"], "EXAM_SUFFIX": ex["state_suffix"],
            "EXAM_PREFIX": ex["prefix"], "EXAM_TAG": ex["tag"],
            "EXAM_PROMISE_FIELD": ex["promise_fields"][0]}
    for k, v in vals.items():
        print("%s=%s" % (k, quote(str(v))))
    return 0


def _cmd_guard(a):
    try:
        prefix = a.prefix or exam(a.exam)["prefix"]
        state, reasons = guard(a.ledger, a.evidence_dir, a.run, a.commit, a.rerun_reason,
                               prefix=prefix)
    except ExamInvalid as e:
        print(str(e))
        return 4
    print("exam %s: run %s on %s%s" % (state, a.run, a.commit,
                                       ("; RERUN, reason logged: %r; overriding: %s"
                                        % (a.rerun_reason, "; ".join(reasons))) if reasons else ""))
    if a.record and state != "resume":
        _append(a.ledger, {"event": "start", "run": a.run, "commit": a.commit,
                           "exam": a.exam,
                           "state": state, "rerun_reason": a.rerun_reason,
                           "overrode": reasons})
    return 0


def _cmd_finish(a):
    _append(a.ledger, {"event": "finish", "run": a.run, "commit": a.commit,
                       "evidence": a.evidence,
                       "evidence_sha256": sha256(a.evidence) if os.path.exists(a.evidence) else None})
    print("ledger: exam %s finished" % a.run)
    return 0


def _cmd_wrap(a):
    with open(a.exam_json, encoding="utf-8") as fh:
        result = json.load(fh)
    with open(a.text, encoding="utf-8") as fh:
        text = fh.read()
    if os.path.exists(a.out):
        print("REFUSED: %s exists; a results file is never overwritten" % a.out)
        return 4
    inputs = {}
    for spec in a.input or ():
        label, _, path = spec.partition("=")
        if not path:
            continue
        if os.path.isdir(path):
            inputs[label] = {"path": path, "kind": "directory"}
        elif os.path.exists(path):
            inputs[label] = {"path": path, "sha256": sha256(path)}
        else:
            inputs[label] = {"path": path, "missing": True}
    out = {"schema": EVIDENCE_SCHEMA,
           "generated_utc": datetime.datetime.now(datetime.timezone.utc)
           .strftime("%Y-%m-%dT%H:%M:%SZ"),
           "run": a.run, "exam_set": a.exam,
           "release": a.release or exam(a.exam)["release"],
           "tree_commit": a.commit, "commit_source": "host: git rev-parse HEAD of the measured "
           "tree, passed into each container as EXACTDOC_GIT_COMMIT (as gate_full.sh does)",
           "exam_scripts_commit": a.scripts_commit, "image": {"ref": a.image_ref, "id": a.image_id},
           "rerun_reason": a.rerun_reason or None,
           "synthetic": bool(result.get("synthetic")),
           "verdict": {"valid": result.get("valid"), "announce": result.get("announce"),
                       "R1": (result.get("R1") or {}).get("pass"),
                       "R2": (result.get("R2") or {}).get("pass"),
                       "R3": (result.get("R3") or {}).get("pass")},
           "inputs": inputs, "exam": result, "text": text}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print("wrote %s (announce: %s)" % (a.out, "yes" if result.get("announce") else "no"))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verdict")
    v.add_argument("--exam", default=DEFAULT_EXAM, choices=sorted(EXAMS))
    v.add_argument("--manifest", required=True)
    v.add_argument("--manifest-sha256", default=None,
                   help="replaces the exam's registered hash (the dry run's synthetic set)")
    v.add_argument("--product", required=True)
    v.add_argument("--word", required=True)
    v.add_argument("--raw")
    v.add_argument("--cli-exits")
    v.add_argument("--docs")
    v.add_argument("--commit")
    v.add_argument("--tree", default=os.getcwd(), help="the measured tree (for exactdoc's exit codes)")
    v.add_argument("--json")
    v.add_argument("--text")
    m = sub.add_parser("verify-manifest")
    m.add_argument("manifest")
    m.add_argument("--exam", default=DEFAULT_EXAM, choices=sorted(EXAMS))
    m.add_argument("--sha256", default=None,
                   help="replaces the exam's registered hash and count (the dry run)")
    m.add_argument("--pdfs")
    m.add_argument("--expect-promised", type=int, default=None,
                   help="refuse unless exactly N documents are promised")
    rs = sub.add_parser("rescore-r3", help="a recorded exam's R3 under another rule (reported)")
    rs.add_argument("--exam", default=DEFAULT_EXAM, choices=sorted(EXAMS))
    rs.add_argument("--rule", default="v2", choices=sorted(R3_RULES))
    rs.add_argument("--manifest", required=True)
    rs.add_argument("--product", required=True)
    rs.add_argument("--word", required=True)
    rs.add_argument("--raw")
    rs.add_argument("--cli-exits")
    rs.add_argument("--commit")
    rs.add_argument("--recorded", help="the recorded exam evidence; its verdict must be reproduced")
    rs.add_argument("--tree", default=os.getcwd())
    rs.add_argument("--json")
    r = sub.add_parser("resolve")
    r.add_argument("--exam", default=DEFAULT_EXAM, choices=sorted(EXAMS))
    r.add_argument("--hold", default=None, help="another set directory (the dry run)")
    r.add_argument("--locate", action="store_true",
                   help="find the manifest in the set directory (by name, else by SHA-256)")
    g = sub.add_parser("guard")
    g.add_argument("--exam", default=DEFAULT_EXAM, choices=sorted(EXAMS))
    g.add_argument("--prefix", default=None, help="results prefix (default: the exam's)")
    g.add_argument("--ledger", required=True)
    g.add_argument("--evidence-dir")
    g.add_argument("--run", required=True)
    g.add_argument("--commit", required=True)
    g.add_argument("--rerun-reason")
    g.add_argument("--record", action="store_true")
    f = sub.add_parser("finish")
    f.add_argument("--ledger", required=True)
    f.add_argument("--run", required=True)
    f.add_argument("--commit", required=True)
    f.add_argument("--evidence", required=True)
    w = sub.add_parser("wrap")
    w.add_argument("out")
    w.add_argument("--exam-json", required=True, help="holdout_exam.py verdict's JSON")
    w.add_argument("--exam", default=DEFAULT_EXAM, choices=sorted(EXAMS))
    w.add_argument("--text", required=True)
    w.add_argument("--input", action="append")
    w.add_argument("--run", default="")
    w.add_argument("--release", default=None, help="default: the exam's release")
    w.add_argument("--commit", default="")
    w.add_argument("--scripts-commit", default="")
    w.add_argument("--image-ref", default="")
    w.add_argument("--image-id", default="")
    w.add_argument("--rerun-reason")
    a = ap.parse_args(argv)
    return {"verdict": _cmd_verdict, "verify-manifest": _cmd_verify, "guard": _cmd_guard,
            "finish": _cmd_finish, "wrap": _cmd_wrap, "resolve": _cmd_resolve,
            "rescore-r3": _cmd_rescore}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
