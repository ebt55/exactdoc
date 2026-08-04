"""Backend parity over the EXPANSION corpus. Measures; never adjudicates.

    python testkit/parity_expansion.py --profile candidate
    python testkit/parity_expansion.py --profile product --only x01 x04 y13
    python testkit/parity_expansion.py --profile candidate --tier unsupported

`backend_parity.py` answers "may the swap ship?" over the gated 16, against
`parity_policy.json`, and its exit code is an authorisation. This file answers a
different question -- "what does the swap do to 29 documents nobody has promised
anything about?" -- and its exit code is never an authorisation of anything.

**Why a separate file rather than `backend_parity.py --expansion`.** The
dangerous function in that module is `record_policy`, which writes measured
floors into the committed acceptance policy. A flag that selects a different
corpus puts the expansion documents one argument-parsing mistake away from
re-flooring the gated policy with numbers measured over documents the policy
does not govern. Here that cannot happen by construction: this module never
imports `record_policy`, never opens `parity_policy.json` for writing, and never
calls `evidence.merge`. It borrows only the pure comparison primitives --
`dims`, `compare`, `DIMENSIONS` -- so that a metric means the same thing in both
files, which is the one thing that SHOULD be shared. `corpus_manifest.py` splits
`verify` from `verify_expansion` for the same reason and states it plainly: the
gate therefore cannot see an expansion problem.

**Output separation.** The payload carries `schema:
exactdoc.parity-expansion-measurement.v1`, `gating: false`, `adjudicated:
false`, `ok: false` and `release_ready: false`, and has no top-level key that
`evidence.validate` reads as a parity verdict. Anything that mistakenly splices
this document into an evidence artifact's `parity` slot therefore fails closed
and reads as "parity did not pass" -- which is the correct answer, because this
measurement never adjudicated anything.

## Refusal parity

Three fixtures are tiered `unsupported`: they are documents the converter is
*expected to refuse*, and a conversion is the bug. For those the comparison is
not a metric comparison at all -- there are no metrics, because there is no
output -- it is whether **both backends refuse identically, with the same typed
error class**. A swap that changed `InteractiveFormError` into a generic
`ParseError`, or that converted a 492-page document the incumbent refused, has
changed the product's contract with its callers even though no fidelity number
moved. Exit codes are an API: `interactive-form` is 19 and `page-limit` is 20,
and a script branching on those is entitled to the same answer after the swap.

## Severity, and why margins appear here without a policy

Each measurable document is compared twice: once with EMPTY margins, which makes
every raw movement visible, and once with the margins from `parity_policy.json`.
Only the `margins` section is read -- never `provisional_shortfalls`,
`ratified_shortfalls` or `expected_divergence`, because those are per-document
waivers for the gated 16 and applying a waiver to a document it was never
measured on would excuse a divergence nobody has looked at. The margins are a
general statement about how far two correct parsers legitimately drift, so they
separate `MAJOR` (worse past the margin) from `minor` (worse, but inside the
band where two correct parsers are expected to disagree). Neither is a verdict.

Exit codes say something narrow:

    0    every document produced a comparison or an expected refusal
    1    the corpus did not match its manifest, or a document could not be
         measured under either backend -- infrastructure, never fidelity
"""
import argparse
import json
import os
import sys
import time

import _paths  # noqa: F401
import backend_parity
import corpus_manifest
import evidence
import harness

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "parity_expansion_out")
SCHEMA = "exactdoc.parity-expansion-measurement.v1"

# Ordered worst-first. The report ranks on this, so a reader sees the documents
# that could sink the migration before the ones that merely moved.
SEVERITY_ORDER = ("REFUSAL-CONTRACT-GAP", "REFUSAL-ASYMMETRY",
                  "REFUSAL-CLASS-MISMATCH", "CONVERT-ASYMMETRY",
                  "MAJOR", "unmeasurable", "minor", "same", "better",
                  "refusal-parity")


def load_margins(path=None):
    """The margins section of the parity policy, and nothing else.

    Returns (margins, source). Every other section of that file is a waiver
    naming a document in the gated 16; this corpus contains none of them, so
    reading one here could only ever excuse a document it does not describe.
    """
    path = path or backend_parity.POLICY_PATH
    with open(path) as f:
        policy = json.load(f)
    margins = {k: v for k, v in (policy.get("margins") or {}).items()
               if not k.startswith("_")}
    return margins, {"path": os.path.basename(path),
                     "policy_profile_id": policy.get("profile_id"),
                     "sections_read": ["margins"],
                     "waivers_applied": False}


def resolve(tier=None, only=None):
    """-> (paths, specs, problems). Fail closed on any identity mismatch.

    Identity is verified over the WHOLE expansion manifest before any subset is
    measured, exactly as `expansion.resolve` does: a corpus that does not match
    its record is not a corpus you can take a subset of.
    """
    manifest = corpus_manifest.load_expansion()
    problems = corpus_manifest.verify_expansion(manifest)
    documents = manifest.get("documents", {})
    paths, specs = [], {}
    for doc_id in sorted(documents):
        spec = documents[doc_id]
        if tier and spec.get("tier") != tier:
            continue
        if only and not any(k in doc_id for k in only):
            continue
        paths.append(corpus_manifest.expansion_fixture_path(doc_id))
        specs[doc_id] = spec
    if only and not paths:
        problems.append(("unknown", ",".join(only)[:40],
                         "--only matched no document in corpus_expansion.json"))
    return paths, specs, problems


def _error_identity(exc):
    """How a refusal is compared: the typed class, plus its stable slug.

    The class name is the comparison key. `code` is recorded beside it because
    that is what the CLI's exit-code table keys on, so a reader can see both the
    Python contract and the process contract in one row.
    """
    return {"error_class": type(exc).__name__,
            "code": getattr(exc, "code", None),
            "message": str(exc)[:200]}


def run_arm(backend, paths, specs, profile, out_root):
    """Convert one backend over the corpus. Refusals are recorded, not raised.

    Mirrors `backend_parity.run`: `options=` is passed explicitly and nothing is
    monkey-patched, so an exported EXACTDOC_BACKEND cannot redirect either arm of
    the comparison that exists to compare them.
    """
    from exactdoc.convert import convert

    options = profile.replace(backend=backend)
    out = os.path.join(out_root, backend)
    os.makedirs(out, exist_ok=True)
    pairs, res = [], {}
    print("\n---- arm %s (%s), %d document(s) ----"
          % (backend, options.profile_id(), len(paths)))
    for p in paths:
        doc_id = os.path.basename(p)
        n = os.path.splitext(doc_id)[0]
        expect_refusal = specs.get(doc_id, {}).get("tier") == "unsupported"
        dx = os.path.join(out, n + ".docx")
        t0 = time.time()
        try:
            convert(p, dx, options=options)
        except Exception as e:
            # Both tiers record the same shape. Whether an exception is the
            # contract being honoured or a failure is decided in `adjudicate`,
            # where BOTH arms are visible -- deciding it here, one arm at a
            # time, is what would hide an asymmetry.
            res[doc_id] = dict(_error_identity(e), src=doc_id, refused=True,
                               convert_s=round(time.time() - t0, 2))
            print("  %-11s [%s] %-30s %s"
                  % ("REFUSED" if expect_refusal else "CONVERT FAIL",
                     backend, n[:30], type(e).__name__))
            continue
        secs = round(time.time() - t0, 2)
        if expect_refusal:
            # Recorded on the arm, adjudicated across both.
            res[doc_id] = {"src": doc_id, "refused": False, "converted": True,
                           "convert_s": secs, "_docx": dx}
            print("  NOT REFUSED [%s] %-30s converted despite unsupported tier"
                  % (backend, n[:30]))
            continue
        pairs.append((p, dx, n, secs))

    if pairs:
        print("  -- rendering %d docx --" % len(pairs))
        harness.batch_docx_to_pdf([q[1] for q in pairs], os.path.join(out, "r"))
        for p, dx, n, secs in pairs:
            doc_id = os.path.basename(p)
            try:
                r = harness.evaluate(p, dx, os.path.join(out, "r"),
                                     save_images=False)
                r["convert_s"] = secs
                r["refused"] = False
                res[doc_id] = r
                print("  " + harness.brief(r))
            except Exception as e:
                res[doc_id] = {"src": doc_id, "refused": False,
                               "eval_error": "%s: %s" % (type(e).__name__, e)}
                print("  EVAL FAIL [%s] %-30s %s" % (backend, n[:30], str(e)[:50]))
    return res


def adjudicate_refusal(doc_id, A, B):
    """-> row. Do both backends refuse this document the same way?

    Four outcomes, and only one of them is parity. The two that matter most are
    the asymmetries: a document the incumbent refuses and the candidate converts
    is a NEW silent failure -- the caller gets a convincing-looking non-form and
    exit 0 instead of exit 19 -- and the reverse is a capability the swap
    removes. Both are contract changes that no fidelity metric would show,
    because a refused document produces no metrics at all.
    """
    ra, rb = bool(A and A.get("refused")), bool(B and B.get("refused"))
    row = {"document": doc_id, "tier": "unsupported",
           "reference": {"refused": ra, "error_class": (A or {}).get("error_class"),
                         "code": (A or {}).get("code")},
           "candidate": {"refused": rb, "error_class": (B or {}).get("error_class"),
                         "code": (B or {}).get("code")}}
    if ra and rb:
        if A.get("error_class") == B.get("error_class"):
            row["verdict"] = "refusal-parity"
            row["detail"] = "both refuse with %s (exit code %s)" % (
                A.get("error_class"), A.get("code"))
        else:
            row["verdict"] = "REFUSAL-CLASS-MISMATCH"
            row["detail"] = ("both refuse but with different typed errors: %s "
                             "(%s) vs %s (%s). A caller branching on the error "
                             "class or the exit code gets a different answer "
                             "after the swap"
                             % (A.get("error_class"), A.get("code"),
                                B.get("error_class"), B.get("code")))
    elif ra != rb:
        refuser, converter = ("reference", "candidate") if ra else \
            ("candidate", "reference")
        row["verdict"] = "REFUSAL-ASYMMETRY"
        row["detail"] = ("%s refuses (%s) and %s converts anyway. The refusal "
                         "contract does not survive the swap for this document"
                         % (refuser, (A if ra else B).get("error_class"),
                            converter))
    else:
        row["verdict"] = "REFUSAL-CONTRACT-GAP"
        row["detail"] = ("neither backend refuses a document tiered unsupported "
                         "-- the refusal contract does not cover it at all")
    return row


def adjudicate(ref, cand, specs, margins):
    """-> (rows, summary). Severity, never authorisation.

    Coverage is anchored on the manifest specs rather than on the intersection
    of what the two arms produced, for the reason `backend_parity.adjudicate`
    documents: two runs that both dropped the same document still agree, and a
    document that fails under both backends would vanish from an intersection
    without vanishing from the corpus.
    """
    rows, counts = [], {k: 0 for k in SEVERITY_ORDER}
    for doc_id in sorted(specs):
        spec = specs[doc_id]
        A, B = ref.get(doc_id), cand.get(doc_id)
        if spec.get("tier") == "unsupported":
            row = adjudicate_refusal(doc_id, A, B)
            counts[row["verdict"]] += 1
            rows.append(row)
            continue

        fatal_a = A is None or A.get("refused") or \
            any(k in A for k in backend_parity.gate.FATAL_KEYS)
        fatal_b = B is None or B.get("refused") or \
            any(k in B for k in backend_parity.gate.FATAL_KEYS)
        if fatal_a or fatal_b:
            # An asymmetry is strictly worse than a mutual failure: a document
            # only the candidate cannot convert is caused by the swap, while one
            # neither can convert is a pre-existing limitation of this corpus.
            verdict = "unmeasurable" if (fatal_a and fatal_b) \
                else "CONVERT-ASYMMETRY"
            def why(side, r, bad):
                if not bad:
                    return "%s ok" % side
                if r is None:
                    return "%s produced no result" % side
                if r.get("refused"):
                    return "%s refused: %s" % (side, r.get("error_class"))
                key = next(k for k in backend_parity.gate.FATAL_KEYS if k in r)
                return "%s %s: %s" % (side, key, str(r[key])[:90])
            rows.append({"document": doc_id, "tier": spec.get("tier"),
                         "verdict": verdict,
                         "detail": "; ".join([why("reference", A, fatal_a),
                                              why("candidate", B, fatal_b)])})
            counts[verdict] += 1
            continue

        worse_major, better_major = backend_parity.compare(A, B, margins)
        worse_raw, better_raw = backend_parity.compare(A, B, {})
        row = {"document": doc_id, "tier": spec.get("tier"),
               "reference": backend_parity.dims(A),
               "candidate": backend_parity.dims(B),
               "worse": [w[0] for w in worse_major],
               "better": [b[0] for b in better_major],
               "worse_raw": [w[0] for w in worse_raw],
               "better_raw": [b[0] for b in better_raw],
               "deltas": {name: round(b - a, 4) for name, a, b in
                          (worse_raw + better_raw) if a is not None
                          and b is not None}}
        if worse_major:
            row["verdict"] = "MAJOR"
        elif worse_raw:
            row["verdict"] = "minor"
        elif better_raw:
            row["verdict"] = "better"
        else:
            row["verdict"] = "same"
        counts[row["verdict"]] += 1
        rows.append(row)

    rows.sort(key=lambda r: (SEVERITY_ORDER.index(r["verdict"]), r["document"]))
    summary = dict(counts)
    summary.update({
        # Explicit and always false. This measurement applied no waiver and no
        # floor, so it cannot report a pass -- and anything that reads this
        # document as a parity verdict must fail closed rather than read a
        # missing key as success.
        "ok": False, "adjudicated": False, "release_ready": False,
        "gating": False,
        "documents": len(rows),
        "blocking": [r["document"] for r in rows
                     if r["verdict"] in SEVERITY_ORDER[:5]]})
    return rows, summary


def report(rows, ref_name, cand_name):
    lines = ["", "%-32s %-6s %-22s %-22s %s"
             % ("document", "tier", ref_name, cand_name, "verdict")]
    for r in rows:
        tier = {"ordinary_digital": "ord", "designed_stress": "stress",
                "unsupported": "unsup"}.get(r.get("tier"), "-")
        if "reference" in r and "page_err" in (r.get("reference") or {}):
            fmt = "pg%+d l%.2f w%.2f p%.2f"
            a, b = r["reference"], r["candidate"]
            left = fmt % (a["page_err"], a["live_text_cov"], a["word_recall"],
                          a["within2pt"])
            right = fmt % (b["page_err"], b["live_text_cov"], b["word_recall"],
                           b["within2pt"])
        elif r.get("tier") == "unsupported":
            left = "%s" % (r["reference"].get("error_class") or "converted")
            right = "%s" % (r["candidate"].get("error_class") or "converted")
        else:
            left, right = "-", "-"
        extra = ""
        if r.get("worse"):
            extra += "  worse:" + ",".join(r["worse"])
        if r.get("better"):
            extra += "  better:" + ",".join(r["better"])
        if r.get("verdict") == "minor" and r.get("worse_raw"):
            extra += "  raw-worse:" + ",".join(r["worse_raw"])
        lines.append("%-32s %-6s %-22s %-22s %s%s"
                     % (r["document"][:32], tier, left[:22], right[:22],
                        r["verdict"], extra))
        if r.get("detail"):
            lines.append("%-32s   %s" % ("", r["detail"][:110]))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile", choices=backend_parity.PROFILE_NAMES,
                    default="candidate",
                    help="complete conversion profile used by BOTH arms; only "
                         "the backend field differs (default: %(default)s)")
    ap.add_argument("--tier", default=None, choices=corpus_manifest.TIERS)
    ap.add_argument("--only", nargs="+", default=None,
                    help="substrings; measure only the matching documents")
    ap.add_argument("--out", default=None)
    ap.add_argument("--json", default=None,
                    help="write the measurement payload here")
    a = ap.parse_args(argv)

    paths, specs, problems = resolve(a.tier, a.only)
    if problems:
        print("expansion corpus does not match corpus_expansion.json:")
        for kind, doc, why in problems:
            print("  %-11s %-30s %s" % (kind, doc[:30], why))
        print("\nRefusing to measure. Numbers computed over bytes that are not "
              "the recorded bytes describe nothing at all.")
        return 1
    if not paths:
        print("no expansion fixtures selected -- nothing to measure.")
        return 1

    profile = backend_parity.conversion_profile(a.profile)
    margins, margin_source = load_margins()
    ref_name, cand_name = "pymupdf", "pdfium"
    out_root = os.path.join(a.out or OUT, a.profile)
    os.makedirs(out_root, exist_ok=True)

    print("EXPANSION PARITY -- NON-GATING MEASUREMENT")
    print("profile        %s (both arms; backend is the only difference)"
          % profile.profile_id())
    print("reference      %s" % profile.replace(backend=ref_name).profile_id())
    print("candidate      %s" % profile.replace(backend=cand_name).profile_id())
    print("documents      %d%s" % (len(paths),
                                   " in tier %s" % a.tier if a.tier else ""))
    print("margins        from %s (margins section only, no waivers)"
          % margin_source["path"])

    t0 = time.time()
    ref = run_arm(ref_name, paths, specs, profile, out_root)
    cand = run_arm(cand_name, paths, specs, profile, out_root)
    rows, summary = adjudicate(ref, cand, specs, margins)

    print(report(rows, ref_name, cand_name))
    print("\n" + ", ".join("%d %s" % (summary[k], k)
                           for k in SEVERITY_ORDER if summary.get(k)))

    env = evidence.environment()
    payload = {
        "schema": SCHEMA,
        "gating": False,
        "adjudicated": False,
        "ok": False,
        "release_ready": False,
        "_note": "Backend parity over the NON-GATING expansion corpus. No "
                 "baseline describes these documents, testkit/gate.py never "
                 "sees them, and parity_policy.json governs none of them. "
                 "Severity is computed from that policy's `margins` section "
                 "alone; no waiver or floor was read or applied.",
        "corpus": "corpus_expansion.json",
        "profile": a.profile,
        "profile_id": profile.profile_id(),
        "reference_backend": ref_name,
        "candidate_backend": cand_name,
        "reference_profile_id": profile.replace(backend=ref_name).profile_id(),
        "candidate_profile_id": profile.replace(backend=cand_name).profile_id(),
        "tier_filter": a.tier,
        "only": sorted(a.only) if a.only else None,
        "subset": bool(a.tier or a.only),
        "margins": margins,
        "margins_source": margin_source,
        "elapsed_s": round(time.time() - t0, 1),
        "git": evidence.git_state(),
        "environment_fingerprint": env.get("fingerprint"),
        "environment_canonical": env.get("canonical"),
        "environment_canonical_mismatches": env.get("canonical_mismatches"),
        "summary": summary,
        "documents": rows,
    }
    path = a.json or os.path.join(out_root, "parity_expansion.json")
    with open(path, "w") as f:
        json.dump(payload, f, indent=1, sort_keys=True)
    print("\nwrote %s" % path)
    print("This measurement gates nothing and authorises nothing. No baseline "
          "describes this corpus and parity_policy.json governs none of it.")

    unmeasured = [r["document"] for r in rows
                  if r["verdict"] in ("unmeasurable", "CONVERT-ASYMMETRY")]
    if unmeasured:
        print("\nExit 1: %d document(s) produced no comparison (%s). That is an "
              "infrastructure or capability failure, not a fidelity judgement."
              % (len(unmeasured), ", ".join(unmeasured)))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
