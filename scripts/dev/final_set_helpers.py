"""Helpers for final_set.sh (WP44). Not part of the package.

    python final_set_helpers.py pick SWEEP --frac 0.4 [--only a b]
        documents whose sweep convert_s is at least FRAC of their criterion-2
        limit (beta_readiness.BAR), slowest first, unsupported ones left out:
        the ones a quiet serial timing has to settle
    python final_set_helpers.py merge PROFILE OUT PART.json...
        one serial-timing payload (exactdoc.serial-timing.v1) from per-document
        runs, each document carrying the machine load recorded beside it
        (PART.load.json: host CPU and other containers before and after)
    python final_set_helpers.py wrap OUT.json --readiness R.json --text R.txt
            --accepted A.sweep.json --input label=path ...
        the evidence file: the scorecard's JSON and text, every input by path
        and SHA-256, the accepted sweep by path and SHA-256 (newline="\\n")
    python final_set_helpers.py docs-done ROWS --sweep SWEEP
        exit 0 when the live Docs rows hold every document the sweep measured
        (the sentinel row aside), else print the missing ones and exit 1

Run with PYTHONPATH=<tree> and cwd=<tree>, so testkit is the measured tree's.
"""
import argparse
import datetime
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _testkit(tree):
    sys.path.insert(0, os.path.join(tree, "testkit"))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _limit(kind, pages, bar):
    if kind == "raw":
        return bar["raw_s_per_page"] * pages
    if pages <= bar["product_flat_pages"]:
        return bar["product_flat_s"]
    return bar["product_s_per_page"] * pages


def pick(a):
    _testkit(a.tree)
    import beta_readiness as br
    with open(a.sweep, encoding="utf-8") as fh:
        sweep = json.load(fh)
    kind = br._profile_kind(sweep.get("profile"))
    if kind not in ("raw", "product"):
        print("not a raw or product sweep: %s" % sweep.get("profile"), file=sys.stderr)
        return 2
    tiers = {d: v.get("tier") for d, v in br.corpus().items()}
    only = {o if o.endswith(".pdf") else o + ".pdf" for o in (a.only or ())}
    rows = []
    for r in sweep.get("documents", ()):
        doc, s, pages = r.get("document"), r.get("convert_s"), r.get("src_pages")
        if not isinstance(s, (int, float)) or not pages or tiers.get(doc) == "unsupported":
            continue
        if only and doc not in only:
            continue
        if s >= a.frac * _limit(kind, pages, br.BAR):
            rows.append((s, doc))
    for _, doc in sorted(rows, reverse=True):
        print(doc)
    return 0


def merge(a):
    rows, profile, machine = [], None, None
    for part in a.parts:
        with open(part, encoding="utf-8") as fh:
            data = json.load(fh)
        profile = profile or data.get("profile")
        machine = machine or data.get("machine")
        load_path = part[:-len(".json")] + ".load.json"
        load = None
        if os.path.exists(load_path):
            with open(load_path, encoding="utf-8") as fh:
                load = json.load(fh)
        for r in data.get("documents", ()):
            r = dict(r)
            r["load"] = load
            rows.append(r)
    payload = {"schema": "exactdoc.serial-timing.v1", "gating": False,
               "profile": profile, "jobs": 1, "repeat": 1,
               "machine": machine, "quiet_rule": a.quiet_rule,
               "documents": rows}
    tmp = a.out + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, a.out)
    print("%s: %d documents" % (a.out, len(rows)))
    return 0


def wrap(a):
    with open(a.readiness, encoding="utf-8") as fh:
        readiness = json.load(fh)
    with open(a.text, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
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
    out = {"schema": "exactdoc.final-set.v1",
           "generated_utc": datetime.datetime.now(datetime.timezone.utc)
           .strftime("%Y-%m-%dT%H:%M:%SZ"),
           "run": a.run, "tree_commit": a.commit, "release": a.release,
           "accepted": {"path": a.accepted, "sha256": sha256(a.accepted)},
           "inputs": inputs, "readiness": readiness, "text": text}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print("wrote %s (verdict: %s)" % (a.out, readiness.get("verdict")))
    return 0


def docs_done(a):
    with open(a.sweep, encoding="utf-8") as fh:
        want = {r["document"] for r in json.load(fh).get("documents", ())
                if r.get("out_pages")}
    have = set()
    if os.path.exists(a.rows):
        with open(a.rows, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    r = json.loads(line)
                    if r.get("doc") and not r["doc"].startswith("_") and "error" not in r:
                        have.add(r["doc"])
    missing = sorted(want - have)
    if missing:
        print("Docs rows missing %d of %d: %s" % (len(missing), len(want),
                                                   " ".join(missing[:12])))
        return 1
    print("Docs rows complete: %d documents" % len(want))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pick")
    p.add_argument("sweep")
    p.add_argument("--tree", default=os.getcwd())
    p.add_argument("--frac", type=float, default=0.4)
    p.add_argument("--only", nargs="*")
    m = sub.add_parser("merge")
    m.add_argument("profile")
    m.add_argument("out")
    m.add_argument("parts", nargs="+")
    m.add_argument("--quiet-rule", default="")
    w = sub.add_parser("wrap")
    w.add_argument("out")
    w.add_argument("--readiness", required=True)
    w.add_argument("--text", required=True)
    w.add_argument("--accepted", required=True)
    w.add_argument("--input", action="append")
    w.add_argument("--run", default="")
    w.add_argument("--commit", default="")
    w.add_argument("--release", default="")
    d = sub.add_parser("docs-done")
    d.add_argument("rows")
    d.add_argument("--sweep", required=True)
    a = ap.parse_args(argv)
    return {"pick": pick, "merge": merge, "wrap": wrap, "docs-done": docs_done}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
