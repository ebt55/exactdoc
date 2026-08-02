"""Google Docs oracle and fail-closed frozen-corpus qualification harness.

``prepare`` locally converts the committed frozen PDF corpus with the named
candidate and writes a binding record.  ``run`` is a qualification, not a
convenient batch uploader: it accepts only that prepared complete DOCX set and
needs per-run affirmative cloud-upload consent::

    python testkit/gdocs_oracle.py prepare testkit/batch
    python testkit/gdocs_oracle.py run testkit/batch --allow-cloud-upload

The resulting ``gdocs_qualification.json`` deliberately contains only safe
basenames and measurements.  In particular it never records local paths,
source text, credentials, or Drive file IDs.  ``explore`` is separately named
for ad-hoc work and must not be used as qualification evidence.
"""
import argparse
import functools
import hashlib
import json
import math
import os
import sys
import shutil
import tempfile
import time

import _paths  # noqa: F401
import harness

PROJECT = _paths.PROJECT
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MANIFEST = os.path.join(HERE, "corpus_manifest.json")
CREDS = os.path.join(PROJECT, "credentials.json")
TOKEN = os.path.join(PROJECT, "token.json")
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
GDOC_MIME = "application/vnd.google-apps.document"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
EVIDENCE_NAME = "gdocs_qualification.json"
PREPARATION_NAME = ".exactdoc-gdocs-preparation.json"
PREPARATION_SCHEMA = "exactdoc.gdocs-preparation.v1"
QUALITY_POLICY_SCHEMA = "exactdoc.gdocs-quality-policy.v1"
DEFAULT_QUALITY_POLICY = os.path.join(HERE, "gdocs_quality_policy.json")
# This is intentionally a qualification candidate, not the shipping PRODUCT.
# ``prepare`` verifies the runtime's named options object resolves to this ID.
CANDIDATE_PROFILE_ID = "pdfium/gdocs/none/refine0@240dpi"
# A delete failure leaves a Drive file behind.  This local-only recovery ledger
# deliberately lives outside a qualification output directory, is gitignored,
# and is never included in evidence or console output.
ORPHAN_LEDGER = os.path.join(PROJECT, ".gdocs_orphans.json")


class QualificationError(RuntimeError):
    """A local validation failure.  ``stage`` is safe to put in evidence."""

    def __init__(self, message, stage="preflight"):
        super().__init__(message)
        self.stage = stage


class RoundtripError(RuntimeError):
    """A Drive operation failed without exposing a remote identifier."""

    def __init__(self, stage):
        super().__init__("Google Docs round trip failed during %s" % stage)
        self.stage = stage


def _preflight_io(function):
    """Translate only local filesystem failures at the qualification boundary."""
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except QualificationError:
            raise
        except PermissionError as exc:
            raise QualificationError("qualification inputs cannot be accessed (permission denied)",
                                     stage="preflight") from exc
        except OSError as exc:
            raise QualificationError("qualification inputs could not be read", stage="preflight") from exc
    return wrapped


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _safe_basename(name):
    """Reject manifest entries that are not plain file names."""
    if not isinstance(name, str) or not name or os.path.basename(name) != name:
        raise QualificationError("manifest contains an unsafe document name")
    return name


@_preflight_io
def _manifest_identity(manifest_path):
    """Safe manifest identity for evidence, based on exact manifest bytes."""
    return {"name": _safe_basename(os.path.basename(manifest_path)),
            "sha256": _sha256(manifest_path)}


def _fixture_dir(manifest, manifest_path):
    """Resolve a custom manifest's fixture directory without accepting absolutes.

    The repository manifest predates this harness and records its directory
    relative to the repository root.  Small qualification manifests instead
    use a directory relative to their own location, which also keeps tests
    hermetic.
    """
    raw = manifest.get("fixtures_dir")
    if not isinstance(raw, str) or not raw or os.path.isabs(raw):
        raise QualificationError("manifest has no safe relative fixtures_dir")
    if os.path.abspath(manifest_path) == os.path.abspath(DEFAULT_MANIFEST):
        base = PROJECT
    else:
        base = os.path.dirname(os.path.abspath(manifest_path))
    directory = os.path.abspath(os.path.join(base, raw))
    if os.path.commonpath([directory, os.path.abspath(base)]) != os.path.abspath(base):
        raise QualificationError("manifest fixtures_dir escapes its allowed root")
    return directory


@_preflight_io
def _source_plan(manifest_path=DEFAULT_MANIFEST):
    """Return the exact, hash-pinned source plan before touching DOCX output."""
    os.stat(manifest_path)
    if not os.path.isfile(manifest_path):
        raise QualificationError("qualification manifest is missing")
    identity = _manifest_identity(manifest_path)
    try:
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError) as exc:
        raise QualificationError("qualification manifest is unreadable") from exc
    documents = manifest.get("documents")
    if not isinstance(documents, dict) or not documents:
        raise QualificationError("qualification manifest has no documents")
    fixtures = _fixture_dir(manifest, manifest_path)
    if not os.path.isdir(fixtures):
        raise QualificationError("frozen fixture directory is missing")

    expected = {}
    for source_name, spec in sorted(documents.items()):
        source_name = _safe_basename(source_name)
        if not source_name.lower().endswith(".pdf") or not isinstance(spec, dict):
            raise QualificationError("manifest has an invalid document entry")
        want_hash = spec.get("sha256")
        if not isinstance(want_hash, str) or len(want_hash) != 64:
            raise QualificationError("manifest has an unpinned source")
        try:
            int(want_hash, 16)
        except ValueError as exc:
            raise QualificationError("manifest has an invalid source hash") from exc
        docx_name = os.path.splitext(source_name)[0] + ".docx"
        if docx_name in expected:
            raise QualificationError("manifest maps multiple sources to one DOCX")
        expected[docx_name] = (source_name, want_hash.lower())

    actual_sources = {n for n in os.listdir(fixtures) if n.lower().endswith(".pdf")}
    source_names = {source for source, _ in expected.values()}
    if actual_sources != source_names:
        raise QualificationError("frozen fixture set does not exactly match manifest")
    plan = []
    for docx_name, (source_name, want_hash) in sorted(expected.items()):
        source_path = os.path.join(fixtures, source_name)
        if not os.path.isfile(source_path):
            raise QualificationError("a required qualification input is not a file")
        if _sha256(source_path) != want_hash:
            raise QualificationError("frozen source hash does not match manifest")
        plan.append({"source_name": source_name, "source_path": source_path,
                     "docx_name": docx_name})
    return identity, plan


def _atomic_json(path, payload):
    """Publish small local metadata atomically, never leaving a valid half-file."""
    parent = os.path.dirname(path)
    fd, temporary = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, sort_keys=True, separators=(",", ":"))
            fh.write("\n")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _preparation_payload(identity, plan, docx_dir, profile_id):
    return {"schema": PREPARATION_SCHEMA, "candidate_profile": profile_id,
            "manifest": identity,
            "documents": [{"name": item["docx_name"],
                           "sha256": _sha256(os.path.join(docx_dir, item["docx_name"]))}
                          for item in plan]}


def _candidate_options():
    """Import the explicit candidate only for local preparation, never a default."""
    from exactdoc.options import PDFIUM_GDOCS_CANDIDATE
    if PDFIUM_GDOCS_CANDIDATE.profile_id() != CANDIDATE_PROFILE_ID:
        raise QualificationError("the named Google Docs candidate profile is inconsistent")
    return PDFIUM_GDOCS_CANDIDATE


@_preflight_io
def prepare(docx_dir, manifest_path=DEFAULT_MANIFEST, converter=None,
            candidate_options=None):
    """Locally generate an exact candidate DOCX set plus binding metadata.

    This deliberately has no Drive service, authentication, Google import or
    consent flag.  A staging directory means an interrupted preparation cannot
    leave a partial target that qualification might mistake for evidence.
    """
    identity, plan = _source_plan(manifest_path)
    options = candidate_options or _candidate_options()
    profile_id = options.profile_id()
    if profile_id != CANDIDATE_PROFILE_ID:
        raise QualificationError("preparation must use the named Google Docs candidate profile")
    if converter is None:
        from exactdoc.convert import convert as converter
    target = os.path.abspath(docx_dir)
    if os.path.exists(target):
        if not os.path.isdir(target) or os.listdir(target):
            raise QualificationError("preparation target must be a new or empty directory")
    parent = os.path.dirname(target)
    if not os.path.isdir(parent):
        raise QualificationError("preparation target parent is missing")
    stage = tempfile.mkdtemp(prefix=".exactdoc-gdocs-prepare-", dir=parent)
    try:
        for item in plan:
            converter(item["source_path"], os.path.join(stage, item["docx_name"]),
                      options=options)
        expected = {item["docx_name"] for item in plan}
        actual = set(os.listdir(stage))
        if actual != expected or not all(os.path.isfile(os.path.join(stage, name))
                                         for name in expected):
            raise QualificationError("preparation did not produce the complete DOCX set")
        _atomic_json(os.path.join(stage, PREPARATION_NAME),
                     _preparation_payload(identity, plan, stage, profile_id))
        if os.path.isdir(target):
            os.rmdir(target)       # it was verified empty before staging began
        os.replace(stage, target)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return {"profile": profile_id, "manifest": identity,
            "preparation": {"name": PREPARATION_NAME,
                            "sha256": _sha256(os.path.join(target, PREPARATION_NAME))}}


@_preflight_io
def qualification_plan(docx_dir, manifest_path=DEFAULT_MANIFEST):
    """Return a source- and preparation-bound plan before Drive authentication.

    This runs before authentication/service construction.  The DOCX directory
    must have exactly one counterpart for every manifest source and nothing
    else, so a partial run can never look like a whole-corpus qualification.
    """
    identity, plan = _source_plan(manifest_path)
    os.stat(docx_dir)
    if not os.path.isdir(docx_dir):
        raise QualificationError("DOCX directory is missing")
    expected = {item["docx_name"] for item in plan}
    if set(os.listdir(docx_dir)) != expected | {PREPARATION_NAME}:
        raise QualificationError("DOCX directory does not exactly match prepared candidate set")
    record_path = os.path.join(docx_dir, PREPARATION_NAME)
    try:
        with open(record_path, encoding="utf-8") as fh:
            record = json.load(fh)
    except (OSError, ValueError) as exc:
        raise QualificationError("preparation record is missing or unreadable") from exc
    entries = record.get("documents") if isinstance(record, dict) else None
    if (not isinstance(record, dict) or record.get("schema") != PREPARATION_SCHEMA or
            record.get("candidate_profile") != CANDIDATE_PROFILE_ID or
            record.get("manifest") != identity or not isinstance(entries, list)):
        raise QualificationError("preparation record does not bind this candidate and manifest")
    hashes = {}
    for entry in entries:
        if (not isinstance(entry, dict) or set(entry) != {"name", "sha256"} or
                not isinstance(entry["name"], str) or
                not isinstance(entry["sha256"], str) or len(entry["sha256"]) != 64):
            raise QualificationError("preparation record is unsafe")
        try:
            int(entry["sha256"], 16)
        except ValueError as exc:
            raise QualificationError("preparation record is unsafe") from exc
        if entry["name"] in hashes:
            raise QualificationError("preparation record repeats a DOCX")
        hashes[entry["name"]] = entry["sha256"].lower()
    if set(hashes) != expected:
        raise QualificationError("preparation record does not cover the exact DOCX set")
    for item in plan:
        docx_path = os.path.join(docx_dir, item["docx_name"])
        if not os.path.isfile(docx_path) or _sha256(docx_path) != hashes[item["docx_name"]]:
            raise QualificationError("prepared DOCX does not match its recorded hash")
        item["docx_path"] = docx_path
    return identity, plan, {"name": PREPARATION_NAME, "sha256": _sha256(record_path)}


def _service(interactive=True):
    """Build the Drive client lazily so tests/preflight need no Google package."""
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds = None
    if os.path.exists(TOKEN):
        creds = Credentials.from_authorized_user_file(TOKEN, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not interactive:
                raise RuntimeError("no valid token; run: gdocs_oracle.py auth")
            if not os.path.exists(CREDS):
                raise RuntimeError("missing %s" % CREDS)
            flow = InstalledAppFlow.from_client_secrets_file(CREDS, SCOPES)
            creds = flow.run_local_server(port=0,
                                          authorization_prompt_message=
                                          "Opening a browser for Google consent...",
                                          success_message="Authorised. You can close this tab.")
        with open(TOKEN, "w") as fh:
            fh.write(creds.to_json())
        try:
            os.chmod(TOKEN, 0o600)
        except OSError:
            pass
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _record_orphan(file_id, ledger_path=ORPHAN_LEDGER):
    """Persist an undeleted Drive ID locally for manual recovery.

    This intentionally has no return value and callers must never print it.
    The small JSON file is opened with owner-only permissions where the OS
    honours POSIX modes; ``chmod`` also narrows an existing ledger.
    """
    if not isinstance(file_id, str) or not file_id:
        raise RuntimeError("Drive delete failed without a usable recovery identifier")
    fd = os.open(ledger_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            os.chmod(ledger_path, 0o600)
        except OSError:
            pass
        with os.fdopen(fd, "r+", encoding="utf-8") as fh:
            try:
                payload = json.load(fh)
            except (ValueError, json.JSONDecodeError):
                payload = {}
            ids = payload.get("file_ids", []) if isinstance(payload, dict) else []
            if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
                raise RuntimeError("orphan ledger has an unsafe format")
            if file_id not in ids:
                ids.append(file_id)
            fh.seek(0)
            fh.truncate()
            json.dump({"schema": "exactdoc.gdocs-orphan-ledger.v1", "file_ids": ids},
                      fh, sort_keys=True)
            fh.write("\n")
    except BaseException:
        # fdopen takes ownership only after it succeeds.
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def _require_clear_orphan_ledger(ledger_path=ORPHAN_LEDGER):
    """Fail closed when a previous cleanup left a recoverable remote file."""
    if not os.path.exists(ledger_path):
        return
    if not os.path.isfile(ledger_path):
        raise QualificationError("orphan ledger is unsafe", stage="preflight")
    try:
        with open(ledger_path, encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError) as exc:
        raise QualificationError("orphan ledger is unreadable", stage="preflight") from exc
    if not isinstance(payload, dict) or payload.get("schema") != "exactdoc.gdocs-orphan-ledger.v1":
        raise QualificationError("orphan ledger is unsafe", stage="preflight")
    ids = payload.get("file_ids")
    if (not isinstance(ids, list) or
            not all(isinstance(file_id, str) and file_id for file_id in ids)):
        raise QualificationError("orphan ledger is unsafe", stage="preflight")
    if ids:
        # Do not interpolate identifiers: console output and evidence must not
        # expose Drive IDs, but an outstanding object still blocks a green run.
        raise QualificationError("unresolved Google Drive cleanup remains", stage="preflight")


def roundtrip(svc, docx_path, out_pdf, media_factory=None, orphan_recorder=_record_orphan):
    """Upload, export, and *always* delete the created Google Doc.

    A failed export still triggers deletion.  A failed deletion overrides an
    otherwise successful export because qualification must not hide an orphan.
    """
    if media_factory is None:
        from googleapiclient.http import MediaFileUpload
        media_factory = MediaFileUpload
    try:
        media = media_factory(docx_path, mimetype=DOCX_MIME, resumable=False)
        meta = {"name": os.path.basename(docx_path), "mimeType": GDOC_MIME}
        created = svc.files().create(body=meta, media_body=media, fields="id").execute()
        fid = created["id"]
    except Exception as exc:
        raise RoundtripError("upload") from exc

    export_error = None
    try:
        data = svc.files().export(fileId=fid, mimeType="application/pdf").execute()
        with open(out_pdf, "wb") as fh:
            fh.write(data)
    except Exception as exc:
        export_error = exc

    try:
        svc.files().delete(fileId=fid).execute()
    except Exception as exc:
        try:
            orphan_recorder(fid)
        except Exception as ledger_exc:
            raise RoundtripError("cleanup") from ledger_exc
        raise RoundtripError("cleanup") from exc
    if export_error is not None:
        raise RoundtripError("export") from export_error
    return out_pdf


# Only values from this known measurement schema enter external evidence.  This
# prevents a future evaluator from accidentally adding text or a local path.
_NUMBER_METRICS = {
    "docx_bytes", "src_chars", "live_chars", "live_text_cov", "raster_frac",
    "n_media", "media_bytes", "src_pages", "out_pages", "src_words", "word_recall",
    "doc_recall", "dx_p50", "dx_p90", "dy_p50", "dy_p90", "within2pt",
    "within5pt", "mean_ssim", "mean_iou",
}
_QUALITY_METRICS = {"page_match", "live_text_cov", "doc_recall", "word_recall", "within2pt"}


def qualification_output_dir(docx_dir):
    """A retry-safe default sibling; never place evidence in prepared inputs."""
    return os.path.abspath(docx_dir) + ".gdocs-qualification"


def _require_external_output(docx_dir, out_dir):
    source = os.path.abspath(docx_dir)
    output = os.path.abspath(out_dir)
    try:
        inside = os.path.commonpath([source, output]) == source
    except ValueError:       # distinct Windows drives are necessarily separate
        inside = False
    if inside:
        raise QualificationError("qualification output must be outside the prepared DOCX directory")
    return output


def _finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _safe_metrics(result):
    """Copy only the known numeric renderer metrics, never arbitrary strings."""
    if not isinstance(result, dict):
        return {}
    safe = {key: result[key] for key in sorted(_NUMBER_METRICS)
            if key in result and _finite_number(result[key])}
    if isinstance(result.get("page_match"), bool):
        safe["page_match"] = result["page_match"]
    if result.get("renderer") in {"supplied", "libreoffice", "gdocs"}:
        safe["renderer"] = result["renderer"]
    for key in ("src_pagesize", "out_pagesize"):
        value = result.get(key)
        if isinstance(value, list) and all(_finite_number(item) for item in value):
            safe[key] = value
    page_drift = result.get("page_dy_p90")
    if isinstance(page_drift, dict) and all(_finite_number(value)
                                             for value in page_drift.values()):
        safe["page_dy_p90"] = {str(key): value for key, value in sorted(page_drift.items(),
                                                                           key=lambda item: str(item[0]))}
    pages = result.get("pages")
    if isinstance(pages, list):
        clean_pages = []
        for page in pages:
            if not isinstance(page, dict):
                continue
            clean = {key: page[key] for key in ("page", "ssim", "iou", "mad")
                     if key in page and _finite_number(page[key])}
            if page.get("note") == "missing":
                clean["note"] = "missing"
            if clean:
                clean_pages.append(clean)
        safe["pages"] = clean_pages
    return safe


def _policy_identity(path):
    return {"name": _safe_basename(os.path.basename(path)), "sha256": _sha256(path)}


def _load_quality_policy(path, manifest_identity):
    """Return a valid policy or a safe failure status; never block collection."""
    if not os.path.isfile(path):
        return None, {"status": "missing", "passed": False, "findings": []}
    try:
        identity = _policy_identity(path)
    except OSError:
        return None, {"status": "malformed", "passed": False, "findings": []}
    try:
        with open(path, encoding="utf-8") as fh:
            policy = json.load(fh)
    except (OSError, ValueError):
        return None, {"status": "malformed", "policy": identity,
                      "passed": False, "findings": []}
    if (not isinstance(policy, dict) or policy.get("schema") != QUALITY_POLICY_SCHEMA or
            policy.get("candidate_profile") != CANDIDATE_PROFILE_ID or
            policy.get("manifest") != manifest_identity):
        return None, {"status": "mismatch", "policy": identity,
                      "passed": False, "findings": []}
    checks = policy.get("per_document")
    if not isinstance(checks, dict) or set(checks) != _QUALITY_METRICS:
        return None, {"status": "malformed", "policy": identity,
                      "passed": False, "findings": []}
    normalised = {}
    for metric, rule in checks.items():
        if metric == "page_match":
            if not isinstance(rule, dict) or rule != {"equals": True}:
                return None, {"status": "malformed", "policy": identity,
                              "passed": False, "findings": []}
            normalised[metric] = rule
            continue
        if not isinstance(rule, dict) or set(rule) != {"min"}:
            return None, {"status": "malformed", "policy": identity,
                          "passed": False, "findings": []}
        if not _finite_number(rule["min"]) or not 0 <= rule["min"] <= 1:
            return None, {"status": "malformed", "policy": identity,
                          "passed": False, "findings": []}
        normalised[metric] = rule
    return normalised, {"status": "valid", "policy": identity, "passed": False, "findings": []}


def _evaluate_quality(rows, checks, state):
    """Evaluate every prepared document and required metric without leaking data."""
    findings = []
    for row in rows:
        metrics = row.get("metrics", {})
        for metric, rule in checks.items():
            value = metrics.get(metric)
            reason = None
            if metric == "page_match":
                if not isinstance(value, bool):
                    reason = "missing"
                elif value != rule["equals"]:
                    reason = "mismatch"
            elif not _finite_number(value):
                reason = "missing"
            elif value < rule["min"]:
                reason = "out-of-bounds"
            if reason:
                findings.append({"docx": row["docx"], "metric": metric, "reason": reason})
    state = dict(state)
    state["findings"] = findings
    state["passed"] = not findings
    return state


def _document_record(item):
    return {"source": item["source_name"], "docx": item["docx_name"],
            "attempted": False, "succeeded": False, "failed": False,
            "timing_s": None, "failure_stage": None}


def _evidence(identity, rows, operational_pass, quality, overall_pass,
              failure_stage=None, preparation=None):
    return {"schema": "exactdoc.gdocs-qualification.v1", "mode": "qualification",
            "candidate_profile": CANDIDATE_PROFILE_ID, "manifest": identity,
            "preparation": preparation, "quality": quality, "documents": rows,
            "operational_pass": bool(operational_pass), "quality_pass": bool(quality.get("passed")),
            "overall_pass": bool(overall_pass), "failure_stage": failure_stage}


def _write_evidence(out_dir, evidence):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, EVIDENCE_NAME)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(evidence, fh, indent=2, sort_keys=True, allow_nan=False)
        fh.write("\n")
    return path


def _write_preflight_evidence(out_dir, evidence):
    """Preflight must not turn an inaccessible report directory into a traceback."""
    try:
        _write_evidence(out_dir, evidence)
    except OSError:
        pass


def run_qualification(docx_dir, out_dir, manifest_path=DEFAULT_MANIFEST,
                       service_factory=_service, evaluator=harness.evaluate,
                       roundtrip_fn=roundtrip, allow_cloud_upload=False,
                       orphan_ledger_path=ORPHAN_LEDGER,
                       quality_policy_path=DEFAULT_QUALITY_POLICY,
                       raise_preflight=False):
    """Execute a complete, consent-gated qualification after local preflight.

    Direct callers must also opt in; that makes consent impossible to lose if a
    future command bypasses ``main``.  Dependency injection keeps policy tests
    completely hermetic.
    """
    if not allow_cloud_upload:
        raise QualificationError("--allow-cloud-upload is required", stage="consent")
    out_dir = _require_external_output(docx_dir, out_dir)
    try:
        _require_clear_orphan_ledger(orphan_ledger_path)
        identity, plan, preparation = qualification_plan(docx_dir, manifest_path)
    except QualificationError as exc:
        # Consent has already been checked by the caller, so recording the
        # rejection is useful evidence; importantly no service was constructed.
        try:
            identity = _manifest_identity(manifest_path)
        except Exception:
            identity = {"name": _safe_basename(os.path.basename(manifest_path)),
                        "sha256": None}
        evidence = _evidence(identity, [], False,
                             {"status": "not-run", "passed": False, "findings": []},
                             False, exc.stage)
        _write_preflight_evidence(out_dir, evidence)
        if raise_preflight:
            raise
        return False, evidence

    rows = [_document_record(item) for item in plan]
    checks, quality = _load_quality_policy(quality_policy_path, identity)
    try:
        svc = service_factory(interactive=False)
    except Exception:
        for row in rows:
            row["failed"] = True
            row["failure_stage"] = "service"
        evidence = _evidence(identity, rows, False, quality, False, "service", preparation)
        _write_evidence(out_dir, evidence)
        return False, evidence

    # Do not create local output before consent and complete preflight.  Once a
    # service exists, the render path is needed by the first export.
    os.makedirs(out_dir, exist_ok=True)
    if roundtrip_fn is roundtrip:
        def invoke_roundtrip(service, docx_path, rendered_path):
            return roundtrip(service, docx_path, rendered_path,
                             orphan_recorder=lambda file_id: _record_orphan(
                                 file_id, orphan_ledger_path))
    else:
        invoke_roundtrip = roundtrip_fn
    any_failure = False
    for item, row in zip(plan, rows):
        row["attempted"] = True
        started = time.monotonic()
        rendered = os.path.join(out_dir, item["docx_name"] + ".gdocs.pdf")
        try:
            invoke_roundtrip(svc, item["docx_path"], rendered)
        except RoundtripError as exc:
            row["failed"] = True
            row["failure_stage"] = exc.stage
            any_failure = True
        except Exception:
            row["failed"] = True
            row["failure_stage"] = "upload"
            any_failure = True
        else:
            try:
                result = evaluator(item["source_path"], item["docx_path"], out_dir,
                                   save_images=True,
                                   img_dir=os.path.join(out_dir, "cmp_" +
                                                        os.path.splitext(item["docx_name"])[0]),
                                   rendered_pdf=rendered)
                if not isinstance(result, dict) or "error" in result:
                    raise RuntimeError("evaluator did not return complete metrics")
                row["metrics"] = _safe_metrics(result)
                row["succeeded"] = True
            except Exception:
                row["failed"] = True
                row["failure_stage"] = "evaluation"
                any_failure = True
        row["timing_s"] = round(time.monotonic() - started, 3)

    operational = not any_failure and all(row["succeeded"] for row in rows)
    if checks is not None:
        quality = _evaluate_quality(rows, checks, quality)
    overall = operational and quality["passed"]
    failure_stage = None
    if not operational:
        failure_stage = next((row["failure_stage"] for row in rows
                              if row["failure_stage"]), "evaluation")
    elif not quality["passed"]:
        failure_stage = "quality-policy"
    evidence = _evidence(identity, rows, operational, quality, overall,
                         failure_stage, preparation)
    _write_evidence(out_dir, evidence)
    return overall, evidence


def run_exploration(docx_dir, source_dirs, out_dir, limit=0, allow_cloud_upload=False):
    """Ad-hoc uploader, intentionally separate from manifest qualification."""
    if not allow_cloud_upload:
        raise QualificationError("--allow-cloud-upload is required", stage="consent")
    # This is only for investigation.  It deliberately returns false for a
    # missing source rather than pretending a subset proved anything.
    sources = {}
    for directory in source_dirs:
        if os.path.isdir(directory):
            for name in os.listdir(directory):
                if name.lower().endswith(".pdf"):
                    sources[os.path.splitext(name)[0]] = os.path.join(directory, name)
    docxs = sorted(name for name in os.listdir(docx_dir) if name.lower().endswith(".docx"))
    if limit:
        docxs = docxs[:limit]
    svc = _service(interactive=False)
    failures = False
    os.makedirs(out_dir, exist_ok=True)
    for docx_name in docxs:
        stem = os.path.splitext(docx_name)[0]
        source = sources.get(stem)
        if source is None:
            failures = True
            print("EXPLORATION FAIL %s (no source)" % docx_name)
            continue
        try:
            roundtrip(svc, os.path.join(docx_dir, docx_name),
                      os.path.join(out_dir, stem + ".gdocs.pdf"))
        except Exception:
            failures = True
            print("EXPLORATION FAIL %s" % docx_name)
    return 1 if failures else 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["auth", "prepare", "run", "explore"])
    ap.add_argument("docx_dir", nargs="?", help="directory of DOCX files")
    ap.add_argument("--allow-cloud-upload", action="store_true",
                    help="explicitly authorise this run to upload DOCX files to Drive")
    ap.add_argument("--manifest", default=DEFAULT_MANIFEST,
                    help="frozen corpus manifest (qualification only)")
    ap.add_argument("--sources", nargs="*", default=[],
                    help="source PDF directories (exploration only)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--quality-policy", default=DEFAULT_QUALITY_POLICY,
                    help="Google Docs quality policy JSON (run only)")
    ap.add_argument("--limit", type=int, default=0,
                    help="exploration only; qualification always runs the full manifest")
    a = ap.parse_args(argv)
    try:
        return _run_main(a, ap)
    except QualificationError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2


def _run_main(a, ap):

    if a.cmd == "auth":
        _service(interactive=True)
        print("token written to", TOKEN)
        return 0
    if not a.docx_dir:
        ap.error("docx_dir is required")
    if a.cmd == "prepare":
        if a.sources or a.limit or a.out:
            ap.error("--sources, --limit and --out are not valid for prepare")
        prepare(a.docx_dir, a.manifest)
        print("candidate preparation completed")
        return 0
    if not a.allow_cloud_upload:
        print("refusing cloud operation: --allow-cloud-upload is required for every run",
              file=sys.stderr)
        return 2
    if a.cmd == "run":
        if a.sources or a.limit:
            ap.error("--sources and --limit are exploration-only; run qualifies the full manifest")
        out = a.out or qualification_output_dir(a.docx_dir)
        try:
            out = _require_external_output(a.docx_dir, out)
        except QualificationError as exc:
            ap.error(str(exc))
        passed, _ = run_qualification(a.docx_dir, out, a.manifest,
                                      allow_cloud_upload=True,
                                      quality_policy_path=a.quality_policy,
                                      raise_preflight=True)
        print("qualification %s; evidence %s" %
              ("passed" if passed else "failed", os.path.join(out, EVIDENCE_NAME)))
        return 0 if passed else 1
    out = a.out or os.path.join(a.docx_dir, "gdocs_exploration")
    return run_exploration(a.docx_dir, a.sources, out, a.limit,
                           allow_cloud_upload=True)


if __name__ == "__main__":
    sys.exit(main())
