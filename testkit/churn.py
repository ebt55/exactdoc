"""Which source words two renders of one document both place, and where.

    python testkit/churn.py SOURCE.pdf ACCEPTED.pdf CURRENT.pdf [--json OUT]
    python testkit/churn.py SOURCE.pdf ACCEPTED.pdf CURRENT.pdf --check-y37
    python testkit/churn.py ... --require "word_recall.current>=0.347" \\
                                --require "dy_p50.common_current<=23.5"

A measurement, never a gate: it reads three PDFs that already exist -- the
source and two renders of it (an accepted sweep's and the current one's) --
and converts, renders and uploads nothing. SOURCE may also be a corpus
document's name (`y37_plos_one_dvipdfmx.pdf`), read from its frozen fixture.

**Why.** A document's `dy_p50` is the median drift over the source words the
render matched (`harness.match_pairs`: nearest same-text word on the same
page). Two renders match different SETS of words, so the median can move
because the set changed, with no word moving: y37 matched 3,496 source words in
the accepted render and 4,191 in WP33's, and its dy_p50 went 27.38 -> 30.96pt
while the words both renders matched stayed at 21.34 -> 21.36pt. This splits
the matched source words into

    common   matched in both renders  (drift read in each render)
    lost     matched in the accepted render only
    gained   matched in the current render only

and reports, per set, the count, dy_p50, within2pt (|(dx, dy)| <= 2pt, as the
harness counts it) and the share with |dy| <= 5pt. The "all" figures are the
harness's own: they reproduce the sweep's word_recall and dy_p50 exactly.

Two figures say how far to trust the split:

    frequent tokens   the share of each set whose text occurs >= 20 times in
                      the source ("the", "of", "1"). Such a token can match a
                      same-text word a line away by coincidence, so a set made
                      mostly of them is weak evidence of placement either way.
    moved             the share of common words whose dy differs by > 2pt
                      between the renders: the same source word matched in a
                      different place, or to a different occurrence.

The SHA-256 of all three PDFs is recorded, so a figure can be tied to the exact
renders it was read from.

**Checks.** `--require PATH>=X` / `PATH<=X` (repeatable) tests a figure of the
report by its dotted path (`--json` shows every path); the exit code is 1 when
any fails. `--check-y37` is condition d of the owner-delegated decision of
2026-10-10 (docs/beta-bar.md, "Exceptions for 0.3.0b1"), run on the final
renders before the tag:

    word_recall.current      >= 0.347   (the y37 recall the decision accepted)
    dy_p50.common_current    <= 23.5    (accepted common 21.34)
    within2pt.drop           <= gate.py's within2pt tolerance (0.05): the
                                current render's within2pt not below the
                                accepted render's beyond the gate's slack
"""
import _paths  # noqa: F401  (sets sys.path)
import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter

import numpy as np

import gate
import harness

SCHEMA = "exactdoc.churn.v1"
# A token this frequent in the source can match a same-text neighbour by
# coincidence. The reviewer's cut (C:\lotmp\scr\wp41\churn.py, 2026-10-10):
# on y37, 80% of the lost and 64% of the gained words are such tokens.
FREQUENT = 20
# A common word "moved" when its dy in one render differs from its dy in the
# other by more than this: the harness's within2pt radius.
MOVED_PT = 2.0
SETS = ("accepted", "current", "common_accepted", "common_current", "lost", "gained")

# DECISION.md condition d (2026-10-10), recorded in docs/beta-bar.md.
Y37_WORD_RECALL = 0.347      # word_recall of the final render, at least
Y37_COMMON_DY_P50 = 23.5     # common words' dy_p50 in the final render, at most


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _y(w):
    """Where a word sits vertically, as the harness reads it: `harness._y`
    (the baseline, amendment 3) when the harness has one, else what the token
    carries -- its 6th field if present, its box top otherwise. Reading dy at
    the box top while the sweep reads the baseline made the "all" figures
    differ from the sweep's (y37 wp42: 27.64 / 32.00)."""
    anchor = getattr(harness, "_y", None)
    if anchor is not None:
        return anchor(w)
    return w[5] if len(w) > 5 else w[2]


def matched(src_words, render_words):
    """{(page_index, src_index): (dx, dy)} for every source word the render
    matched, by the harness's own matching and the harness's own anchor."""
    out = {}
    for i, si, oj in harness.match_pairs(src_words, render_words):
        s, o = src_words[i][si], render_words[i][oj]
        out[(i, si)] = (o[1] - s[1], _y(o) - _y(s))
    return out


def _set_figures(keys, drift):
    if not keys:
        return {"n": 0, "dy_p50": None, "within2pt": None, "dy_le5_share": None}
    dx = np.array([drift[k][0] for k in keys], dtype=float)
    dy = np.abs(np.array([drift[k][1] for k in keys], dtype=float))
    return {"n": len(keys),
            "dy_p50": round(float(np.percentile(dy, 50)), 2),
            "within2pt": round(float((np.hypot(dx, dy) <= 2).mean()), 4),
            "dy_le5_share": round(float((dy <= 5).mean()), 4)}


def churn(src_pdf, accepted_pdf, current_pdf):
    """The report (a dict, schema exactdoc.churn.v1) for one document."""
    sw = harness.page_words(src_pdf)
    A = matched(sw, harness.page_words(accepted_pdf))
    B = matched(sw, harness.page_words(current_pdf))
    total = sum(len(p) for p in sw)
    common = sorted(set(A) & set(B))
    lost = sorted(set(A) - set(B))
    gained = sorted(set(B) - set(A))
    figures = {"accepted": _set_figures(sorted(A), A),
               "current": _set_figures(sorted(B), B),
               "common_accepted": _set_figures(common, A),
               "common_current": _set_figures(common, B),
               "lost": _set_figures(lost, A),
               "gained": _set_figures(gained, B)}
    freq = Counter(w[0] for page in sw for w in page)

    def frequent_share(keys):
        if not keys:
            return None
        return round(sum(1 for i, si in keys if freq[sw[i][si][0]] >= FREQUENT)
                     / len(keys), 4)

    moved = sum(1 for k in common if abs(A[k][1] - B[k][1]) > MOVED_PT)
    w2 = {k: figures[k]["within2pt"] for k in SETS}
    w2["drop"] = (round(w2["accepted"] - w2["current"], 4)
                  if None not in (w2["accepted"], w2["current"]) else None)
    return {
        "schema": SCHEMA,
        "document": os.path.basename(src_pdf),
        "pdfs": {role: {"path": p, "sha256": sha256(p)} for role, p in
                 (("source", src_pdf), ("accepted", accepted_pdf),
                  ("current", current_pdf))},
        "src_words": total,
        "matched": {"accepted": len(A), "current": len(B), "common": len(common),
                    "lost": len(lost), "gained": len(gained)},
        "word_recall": {"accepted": round(len(A) / max(1, total), 4),
                        "current": round(len(B) / max(1, total), 4)},
        "dy_p50": {k: figures[k]["dy_p50"] for k in SETS},
        "within2pt": w2,
        "dy_le5_share": {k: figures[k]["dy_le5_share"] for k in SETS},
        "moved_gt2pt": {"n": moved,
                        "share": round(moved / len(common), 4) if common else None},
        "frequent_tokens": {"min_count": FREQUENT, "lost": frequent_share(lost),
                            "gained": frequent_share(gained),
                            "common": frequent_share(common)},
    }


# ------------------------------------------------------------------ checks
_REQUIRE = re.compile(r"^\s*([A-Za-z0-9_.]+)\s*(>=|<=)\s*(-?[0-9.]+)\s*$")


def parse_require(text):
    """'word_recall.current>=0.347' -> ('word_recall.current', '>=', 0.347)."""
    m = _REQUIRE.match(text)
    if not m:
        raise ValueError("not PATH>=NUMBER or PATH<=NUMBER: %r" % text)
    return m.group(1), m.group(2), float(m.group(3))


def y37_requirements():
    """Condition d of the 2026-10-10 decision, as (path, op, bound, why)."""
    tol = gate.tolerance(gate.METRICS["within2pt"], None)
    return [("word_recall.current", ">=", Y37_WORD_RECALL,
             "DECISION d: word_recall >= 0.347"),
            ("dy_p50.common_current", "<=", Y37_COMMON_DY_P50,
             "DECISION d: common-word dy_p50 <= 23.5pt (accepted common 21.34)"),
            ("within2pt.drop", "<=", tol,
             "DECISION d: within2pt not below the accepted render's by more "
             "than gate.py's tolerance (%g)" % tol)]


def lookup(report, path):
    value = report
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            raise KeyError(path)
        value = value[part]
    return value


def check(report, requirements):
    """[{require, value, ok, why}] -- a missing or non-numeric figure fails."""
    out = []
    for req in requirements:
        path, op, bound = req[:3]
        why = req[3] if len(req) > 3 else ""
        try:
            value = lookup(report, path)
        except KeyError:
            value = None
        ok = (isinstance(value, (int, float)) and not isinstance(value, bool) and
              (value >= bound if op == ">=" else value <= bound))
        out.append({"require": "%s %s %g" % (path, op, bound), "value": value,
                    "ok": bool(ok), "why": why})
    return out


# ------------------------------------------------------------------ output
def render(report, checks=None):
    m, f = report["matched"], report
    lines = ["%s: %d source words; matched accepted %d, current %d; common %d, "
             "lost %d, gained %d" % (report["document"], report["src_words"],
                                     m["accepted"], m["current"], m["common"],
                                     m["lost"], m["gained"]),
             "word_recall accepted %.4f -> current %.4f"
             % (f["word_recall"]["accepted"], f["word_recall"]["current"]), ""]
    labels = {"accepted": "accepted (all)", "current": "current (all)",
              "common_accepted": "common, accepted pos", "common_current":
              "common, current pos", "lost": "lost, accepted pos",
              "gained": "gained, current pos"}

    def fmt(v, spec):
        return "-" if v is None else spec % v

    for k in SETS:
        n = (m[k] if k in m else m["common"])
        lines.append("  %-22s n=%5d  dy_p50=%7s  within2pt=%7s  dy<=5pt=%7s" % (
            labels[k], n, fmt(f["dy_p50"][k], "%.2f"), fmt(f["within2pt"][k], "%.4f"),
            fmt(f["dy_le5_share"][k], "%.4f")))
    mv, ft = f["moved_gt2pt"], f["frequent_tokens"]
    lines += ["", "common words whose dy changed > %gpt: %d (%s)"
              % (MOVED_PT, mv["n"], fmt(None if mv["share"] is None
                                        else 100 * mv["share"], "%.1f%%")),
              "share of tokens occurring >= %dx in the source: lost %s, gained %s, "
              "common %s" % (ft["min_count"], fmt(ft["lost"], "%.2f"),
                             fmt(ft["gained"], "%.2f"), fmt(ft["common"], "%.2f")),
              ""]
    for role in ("source", "accepted", "current"):
        lines.append("  sha256 %-8s %s  %s" % (role, f["pdfs"][role]["sha256"],
                                               f["pdfs"][role]["path"]))
    if checks:
        lines.append("")
        for c in checks:
            lines.append("  %s  %s (value %s)%s" % (
                "PASS" if c["ok"] else "FAIL", c["require"], c["value"],
                "  -- " + c["why"] if c["why"] else ""))
    return "\n".join(lines)


def _source(path):
    if os.path.exists(path):
        return path
    import rescore                         # a corpus document's name
    return rescore.source_of(path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("source", help="the source PDF, or a corpus document's name")
    ap.add_argument("accepted", help="the accepted sweep's render of it (PDF)")
    ap.add_argument("current", help="the current sweep's render of it (PDF)")
    ap.add_argument("--json", help="also write the report here")
    ap.add_argument("--require", action="append", default=[],
                    help="PATH>=X or PATH<=X on a figure of the report; repeatable")
    ap.add_argument("--check-y37", action="store_true",
                    help="condition d of the 2026-10-10 y37 decision "
                         "(docs/beta-bar.md, Exceptions for 0.3.0b1)")
    a = ap.parse_args(argv)
    try:
        requirements = [parse_require(r) for r in a.require]
    except ValueError as e:
        ap.error(str(e))
    if a.check_y37:
        requirements += y37_requirements()
    report = churn(_source(a.source), a.accepted, a.current)
    checks = check(report, requirements) if requirements else None
    if checks is not None:
        report["checks"] = checks
    print(render(report, checks))
    if a.json:
        with open(a.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(report, fh, indent=1, sort_keys=True)
            fh.write("\n")
    return 1 if checks and not all(c["ok"] for c in checks) else 0


if __name__ == "__main__":
    sys.exit(main())
