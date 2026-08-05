"""The acceptance policy for the EXPANSION corpus, and the reader that binds it.

`parity_policy.json` governs the gated 16 and nothing else. That is not a
limitation to work around -- it is the separation `docs/corpus-expansion.md` §2
exists to protect, and `parity_expansion.py` states it plainly: it reads only
that file's `margins` section, "because those are per-document waivers for the
gated 16 and applying a waiver to a document it was never measured on would
excuse a divergence nobody has looked at."

So an expansion finding had nowhere to be ratified. Writing one into the gated
policy would have produced three defects at once, each independently
disqualifying:

  * **unreachable** -- `backend_parity.adjudicate` never sees an expansion
    document, because it is not in the gated manifest, and `parity_expansion`
    refuses the waiver sections by design. The entry would be enforced by
    nothing, in the one file whose stated purpose is being data the gate
    executes rather than prose a reader is trusted to apply;
  * **falsely bound** -- every gated entry carries `corpus_manifest_sha256`, and
    an expansion document does not live in that manifest. The binding would name
    a corpus that does not contain the document;
  * **cross-contaminating** -- the two corpora would share one acceptance record,
    so a gated re-record and an expansion re-record could not be told apart.

This module is the artifact that was missing. It is deliberately a SEPARATE file
with its OWN corpus pin and its OWN profile sections, and the reader refuses to
read one artifact as the other in either direction.

## What this reader does, and what it does not

`parity_expansion.py` measures and never adjudicates; its exit code is never an
authorisation. Applying a ratification here does not change that. A ratified
finding is **annotated and counted**, never converted into a pass: the row keeps
its measured verdict alongside `ratified: true`, and the module's exit code
still says only whether every document could be measured.

What the reader does enforce is the policy's own integrity, and it fails closed
on all of it -- a corpus that has moved, a section that is present but
unreadable, an entry naming a document the corpus does not contain, a floor
breached, or an entry that has stopped describing anything. Those are
infrastructure failures, in the same class as a corpus that does not match its
manifest, and they are reported as errors rather than absorbed.

## Why entries are keyed by profile

The expansion corpus is measured at two named profiles -- the candidate
(`pdfium/gdocs/none/refine0@240dpi`) and the shipping settings
(`pymupdf/standard/libreoffice/refine3@240dpi`) -- and a finding at one says
nothing about the other. Sections are keyed by the full profile ID of the run,
only the matching section is ever selected, and nothing is borrowed across the
boundary. That is the same rule `backend_parity._policy_profile_errors`
enforces, applied to a file that must serve more than one profile at once.
"""
import datetime
import hashlib
import json
import os

import _paths  # noqa: F401
import backend_parity

ROOT = os.path.dirname(os.path.abspath(__file__))
POLICY_PATH = os.path.join(ROOT, "expansion_parity_policy.json")
CORPUS_PATH = os.path.join(ROOT, "corpus_expansion.json")
SCHEMA = "exactdoc.expansion-parity-policy.v1"

# Keys that only ever appear in the GATED policy. Seeing one here means somebody
# handed this reader `parity_policy.json`, and reading it as an expansion policy
# would apply gated waivers to expansion documents -- the exact contamination
# this artifact was split out to prevent.
_GATED_ONLY_KEYS = {"provisional_shortfalls", "ratified_shortfalls",
                    "expected_divergence", "candidate_backend_floors"}

# All eight required, all checked. A ratification without an owner and a way to
# expire is an unbounded waiver wearing the word; without evidence it is a claim
# nobody can re-check; without a floor it excuses anything.
_ENTRY_FIELDS = {"dimensions", "floors", "reference_at_record", "tier",
                 "defect", "reason", "evidence", "measured_on",
                 "ratified_by", "ratified_on", "issue", "review_condition",
                 "authorization_provenance"}


class PolicyError(Exception):
    """The policy cannot be applied. Never silently downgraded to 'no policy'."""


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _clean(d):
    return {k: v for k, v in d.items() if not k.startswith("_")}


def load(path=None, corpus_path=None):
    """-> policy dict. Raises PolicyError on anything unreadable.

    A missing file is NOT an error: the expansion corpus is non-gating and may
    legitimately have no ratified findings at all. A file that exists and cannot
    be trusted is an error, because the alternative is measuring against half a
    rule.
    """
    path = path or POLICY_PATH
    corpus_path = corpus_path or CORPUS_PATH
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            policy = json.load(fh)
    except (OSError, ValueError) as exc:
        raise PolicyError("expansion parity policy is unreadable: %s" % exc)
    if not isinstance(policy, dict):
        raise PolicyError("expansion parity policy is not an object")

    stray = _GATED_ONLY_KEYS & set(policy)
    if stray:
        raise PolicyError(
            "this is the GATED parity policy, not the expansion policy: it "
            "carries %s. The two corpora keep separate acceptance records on "
            "purpose (docs/corpus-expansion.md section 2); reading one as the "
            "other would apply waivers for the gated 16 to documents they were "
            "never measured on." % ", ".join(sorted(stray)))
    if policy.get("schema") != SCHEMA:
        raise PolicyError("expansion parity policy schema is %r, expected %r"
                          % (policy.get("schema"), SCHEMA))

    corpus = policy.get("corpus")
    if not isinstance(corpus, dict) or not isinstance(corpus.get("sha256"), str):
        raise PolicyError("expansion parity policy does not pin its corpus")
    actual = _sha256(corpus_path)
    if corpus["sha256"] != actual:
        raise PolicyError(
            "expansion parity policy is pinned to a different corpus: the "
            "policy pins sha256 %s, and %s is sha256 %s. Re-pin the policy and "
            "re-check every entry against the corpus it now describes; a floor "
            "measured over other bytes describes nothing."
            % (corpus["sha256"], os.path.basename(corpus_path), actual))

    profiles = policy.get("profiles")
    if not isinstance(profiles, dict):
        raise PolicyError("expansion parity policy has no `profiles` object")
    for profile_id in _clean(profiles):
        if not backend_parity.PROFILE_ID_RE.match(profile_id):
            raise PolicyError(
                "expansion parity policy section %r is not a full profile ID -- "
                "backend, output profile, oracle and DPI must all be named"
                % profile_id)
    return policy


def entries_for(policy, profile_id, documents=None):
    """-> {doc_id: entry} for THIS profile only. Raises on a malformed section.

    `documents` is the expansion manifest's document map when available; entries
    naming a document outside it are refused, because a ratification for a
    document the corpus does not contain cannot have been measured.
    """
    if not policy:
        return {}
    if not backend_parity.PROFILE_ID_RE.match(profile_id or ""):
        raise PolicyError("run profile %r is not a full profile ID" % profile_id)
    section = _clean(policy.get("profiles") or {}).get(profile_id)
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise PolicyError("profiles/%s is not an object" % profile_id)
    findings = _clean(section.get("ratified_findings") or {})
    out = {}
    for doc_id, entry in findings.items():
        where = "profiles/%s/ratified_findings/%s" % (profile_id, doc_id)
        if os.path.basename(doc_id) != doc_id or not doc_id:
            raise PolicyError("%s: unsafe document name" % where)
        if documents is not None and doc_id not in documents:
            raise PolicyError(
                "%s names a document that is not in the expansion corpus. A "
                "ratification is a statement about a measurement; there is no "
                "measurement of a document the corpus does not contain." % where)
        if not isinstance(entry, dict) or set(entry) != _ENTRY_FIELDS:
            raise PolicyError(
                "%s must carry exactly %s"
                % (where, ", ".join(sorted(_ENTRY_FIELDS))))
        dims = entry["dimensions"]
        if (not isinstance(dims, list) or not dims
                or any(d not in backend_parity.DIMENSIONS for d in dims)
                or len(set(dims)) != len(dims)):
            raise PolicyError(
                "%s: dimensions must be a non-empty list of distinct gated "
                "dimensions. A ratification names the dimensions it covers, so "
                "a NEW divergence on this document still blocks." % where)
        for key in ("floors", "reference_at_record"):
            values = entry[key]
            if not isinstance(values, dict) or not values:
                raise PolicyError("%s: %s must be a non-empty object"
                                  % (where, key))
            for name, value in values.items():
                if name not in backend_parity.DIMENSIONS or not backend_parity.gate.is_number(value):
                    raise PolicyError("%s: %s/%s is not a gated numeric metric"
                                      % (where, key, name))
        missing = [d for d in dims if d not in entry["floors"]]
        if missing:
            raise PolicyError(
                "%s: floored on nothing for %s -- an unbounded waiver is a "
                "waiver of anything" % (where, ", ".join(missing)))
        try:
            datetime.date.fromisoformat(entry["measured_on"])
            datetime.date.fromisoformat(entry["ratified_on"])
        except (TypeError, ValueError):
            raise PolicyError("%s: measured_on and ratified_on must be ISO dates"
                              % where)
        for field in ("tier", "defect", "reason", "evidence", "ratified_by",
                      "issue", "review_condition", "authorization_provenance"):
            if not isinstance(entry[field], str) or not entry[field].strip():
                raise PolicyError("%s: %s must be a non-empty string"
                                  % (where, field))
        out[doc_id] = entry
    return out


def check_entry(doc_id, entry, worse, reference, candidate):
    """-> list of failures for one measured document against its entry.

    Two directions, both of which have already caused real damage elsewhere in
    this repository:

    * **below its floor** -- the document regressed past what was signed for;
    * **stale** -- it is no longer worse on any dimension the entry names, so
      the entry describes nothing while still excusing the document, and the
      next real regression on it would pass unremarked.

    A dimension that is worse and NOT named by the entry is not this function's
    business: it stays in `worse` and the caller keeps reporting it, which is
    how a ratification covers a known divergence without covering the document.
    """
    failures = []
    covered = set(entry["dimensions"])
    still_worse = covered & set(worse)
    if not still_worse:
        failures.append(
            (doc_id, "stale", "ratified as worse on %s, but no longer worse on "
                              "any of them. Delete the entry or re-measure it; "
                              "a waiver for a difference that no longer exists "
                              "hides the next one."
             % ", ".join(sorted(covered))))
    for name in sorted(covered):
        floor = entry["floors"].get(name)
        value = (candidate or {}).get(name)
        if not backend_parity.gate.is_number(value):
            failures.append((doc_id, "no-metric",
                             "ratified on %s but the candidate did not produce "
                             "it" % name))
            continue
        spec = backend_parity.gate.METRICS.get(name, {})
        tol = backend_parity.gate.tolerance(spec, floor)
        bad = (value > floor + tol) if name in backend_parity.LOWER_IS_BETTER \
            else (value < floor - tol)
        if bad:
            failures.append((doc_id, "below-floor",
                             "%s %.4g against its ratified floor of %.4g"
                             % (name, value, floor)))
    return failures


def apply(rows, policy, profile_id, documents=None):
    """Annotate measured rows with their ratifications. -> (rows, failures).

    Annotates; never converts a verdict into a pass. `parity_expansion` measures
    and does not adjudicate, and a ratification recorded here does not change
    that -- the row keeps the verdict the measurement produced, with
    `ratified: true` beside it, so a reader can see both what was measured and
    what somebody signed for.
    """
    entries = entries_for(policy, profile_id, documents)
    failures = []
    seen = set()
    for row in rows:
        entry = entries.get(row.get("document"))
        if entry is None:
            continue
        seen.add(row["document"])
        row["ratified"] = True
        row["ratified_dimensions"] = list(entry["dimensions"])
        row["ratified_issue"] = entry["issue"]
        failures.extend(check_entry(row["document"], entry,
                                    row.get("worse") or [],
                                    row.get("reference") or {},
                                    row.get("candidate") or {}))
    for doc_id in sorted(set(entries) - seen):
        failures.append((doc_id, "unmeasured",
                         "ratified for this profile but not measured in this "
                         "run. A ratification that no run checks is a claim "
                         "nobody is testing."))
    return rows, failures
