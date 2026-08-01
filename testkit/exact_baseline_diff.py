"""Did this run reproduce the recorded baseline EXACTLY?

The gate answers a weaker question. It passes within a tolerance, because two
runs of the same code on the same machine legitimately wobble. That is the right
rule for "has the converter regressed?" and the wrong one for "did this refactor
change layout?" -- a change that moves a value by less than the tolerance has
still moved it, and a refactor whose whole claim is that it touched no layout
should be held to bit-equality.

So this exists for changes that assert neutrality: the profile/oracle split, the
permissive runtime boundary, an I/O rewrite. Run the lanes, then run this. It
compares every recorded value with `==`.

    python testkit/runall.py
    python testkit/exact_baseline_diff.py

Exit 0 means nothing moved. Exit 1 names what did. Exit 2 means it compared
nothing, which is not a pass -- a comparison that inspects zero values is the
same false green this repository has now found in three separate test files.
"""
import json
import os
import sys

import _paths  # noqa: F401
from _paths import PROJECT

BASELINE = os.path.join(PROJECT, "testkit", "gate_baseline.json")
BATCH = os.path.join(PROJECT, "testkit", "batch")

# Metrics the baseline records but the per-document results derive rather than
# store. Keeping this explicit: silently skipping an absent key would drop
# `page_err`, and pagination is the largest open defect class in this project.
DERIVED = {"page_err": lambda r: (None if r.get("out_pages") is None
                                  or r.get("src_pages") is None
                                  else r["out_pages"] - r["src_pages"])}


def load_lane(lane):
    path = os.path.join(BATCH, "lane_" + lane, "results.json")
    if not os.path.exists(path):
        return None, "no results at %s -- run testkit/runall.py first" % path
    data = json.load(open(path))
    if isinstance(data, dict):
        for key in ("documents", "rows", "results"):
            if isinstance(data.get(key), (list, dict)):
                data = data[key]
                break
    out = {}
    if isinstance(data, dict):
        for k, v in data.items():
            out[os.path.basename(str(k))] = v
    else:
        for row in data:
            if not isinstance(row, dict):
                continue
            for key in ("src", "doc", "document", "name", "pdf", "file"):
                if row.get(key):
                    out[os.path.basename(str(row[key]))] = row
                    break
    return out, None


def value(row, metric):
    v = row.get(metric)
    if v is None and metric in DERIVED:
        v = DERIVED[metric](row)
    return v


def main():
    base = json.load(open(BASELINE))
    lanes = base.get("lanes") or {}
    moved, checked, absent = [], 0, []

    for lane, rec in sorted(lanes.items()):
        got, err = load_lane(lane)
        if err:
            print("  %-8s SKIPPED: %s" % (lane, err))
            continue
        for doc, want in sorted((rec.get("documents") or {}).items()):
            row = got.get(doc)
            if row is None:
                absent.append("%s/%s" % (lane, doc))
                continue
            for metric, wv in sorted(want.items()):
                if isinstance(wv, bool) or not isinstance(wv, (int, float)):
                    continue
                gv = value(row, metric)
                checked += 1
                if gv is None:
                    moved.append((lane, doc, metric, wv, "MISSING"))
                elif float(gv) != float(wv):
                    moved.append((lane, doc, metric, wv, gv))

    print("compared %d recorded values across %d lane(s)" % (checked, len(lanes)))
    if absent:
        print("%d document(s) absent from results: %s"
              % (len(absent), ", ".join(absent[:8])))
        return 1
    if checked == 0:
        print("ZERO VALUES COMPARED. That is not a pass: either the lanes did "
              "not run or the result schema changed. A comparison that inspects "
              "nothing cannot report a regression.")
        return 2
    if moved:
        print("%d value(s) MOVED:" % len(moved))
        for lane, doc, metric, wv, gv in moved[:60]:
            print("  %-8s %-26s %-14s %s -> %s" % (lane, doc, metric, wv, gv))
        print("\nA change claiming to be layout-neutral moved a measured value. "
              "Attribute it before merging.")
        return 1
    print("ZERO MOVED -- every recorded value reproduced exactly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
