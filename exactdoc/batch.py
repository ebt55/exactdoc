"""Deterministic, bounded local batch conversion.

The module is deliberately local-only: batch jobs do not invoke a cloud
oracle, and JSON reports contain relative names and stable error summaries
rather than content or machine paths.
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Optional

from .convert import convert
from .errors import (ConfigurationError, ExactdocError, OcrRequiredError,
                     ResourceLimitError)
from .scan import inspect_pdf

MAX_DOCUMENTS = 500
MAX_PAGES_PER_DOCUMENT = 250
MAX_PAGES_PER_RUN = 2000
MAX_BYTES_PER_DOCUMENT = 250 * 1024 * 1024
MAX_WORKERS = 4
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class BatchItem:
    source: Path
    relative_input: str
    destination: Optional[Path]
    relative_output: Optional[str]


def _relative(path):
    return path.as_posix()


def _is_reparse(path):
    try:
        return path.is_symlink() or bool(path.stat().st_file_attributes & 0x400)
    except (AttributeError, OSError):
        return path.is_symlink()


def discover(input_dir, out_dir, recursive=False):
    """Find PDFs in deterministic relative order without traversing reparse dirs."""
    root = Path(input_dir).resolve()
    output = Path(out_dir).resolve()
    if not root.is_dir():
        raise ConfigurationError("--input-dir must name an existing directory")
    found = []
    output_inside_input = _is_within(output, root)
    for current, dirs, files in os.walk(root, followlinks=False):
        cur = Path(current)
        # Excluding output avoids converting our own results when it is nested.
        dirs[:] = [d for d in dirs if not _is_reparse(cur / d) and
                   not (output_inside_input and _is_within((cur / d).resolve(), output))]
        for name in files:
            candidate = cur / name
            if candidate.suffix.lower() == ".pdf" and not _is_reparse(candidate):
                found.append(candidate)
        if not recursive:
            dirs[:] = []
    found.sort(key=lambda p: _relative(p.relative_to(root)).casefold())
    return found


def _is_within(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def make_items(input_dir, out_dir, recursive=False):
    root, output = Path(input_dir).resolve(), Path(out_dir).resolve()
    sources = discover(root, output, recursive=recursive)
    if not sources:
        raise ConfigurationError("batch input directory contains no PDF files")
    if len(sources) > MAX_DOCUMENTS:
        raise ResourceLimitError("batch contains more than 500 PDF documents")
    items = []
    seen = set()
    for source in sources:
        rel = source.relative_to(root)
        dest_rel = rel.with_suffix(".docx") if recursive else Path(rel.name).with_suffix(".docx")
        key = _relative(dest_rel).casefold()
        if key in seen:
            raise ConfigurationError("batch inputs map to the same output name")
        seen.add(key)
        items.append(BatchItem(source, _relative(rel), output / dest_rel,
                               _relative(dest_rel)))
    return items


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()


def _safe_error(exc):
    if isinstance(exc, ExactdocError):
        return exc.code, exc.message
    return "failed", "conversion failed"


def _write_json(path, report):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=".exactdoc-",
                                     suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(report, f, sort_keys=True, indent=2)
            f.write("\n")
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def _report_path_key(path):
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _validate_report_path(path, items):
    """Reject report locations that could overwrite a source or DOCX result."""
    report = Path(path)
    if report.suffix.lower() != ".json":
        raise ConfigurationError("--result-json must use a .json filename")
    if report.exists() and report.is_dir():
        raise ConfigurationError("--result-json must name a file, not a directory")
    key = _report_path_key(report)
    protected = {_report_path_key(item.source) for item in items}
    protected.update(_report_path_key(item.destination) for item in items
                     if item.destination is not None)
    if key in protected:
        raise ConfigurationError("--result-json must not replace an input or output file")


def run(items, *, backend, dpi, refine_rounds, output_profile, oracle,
        allow_cloud_upload=False, workers=1, continue_on_error=False,
        overwrite=False, scan_only=False, verbose=False, result_json=None,
        recursive=False):
    """Run items serially; return a content-safe, JSON-serializable report."""
    if not 1 <= workers <= MAX_WORKERS:
        raise ConfigurationError("--workers must be between 1 and 4")
    if workers != 1:
        raise ConfigurationError("batch conversion currently supports --workers 1 only")
    if oracle == "gdocs":
        raise ConfigurationError("batch conversion cannot use the Google Docs oracle")
    if len(items) > MAX_DOCUMENTS:
        raise ResourceLimitError("batch contains more than 500 PDF documents")
    if result_json:
        _validate_report_path(result_json, items)
    # Cheap byte limits and output conflicts are checked before parsing or
    # publishing any source, so a bad late member cannot produce a partial run.
    for item in items:
        if item.source.stat().st_size > MAX_BYTES_PER_DOCUMENT:
            raise ResourceLimitError("input exceeds the 250 MiB file limit")
    if not scan_only:
        for item in items:
            if item.destination.exists() and not overwrite:
                raise ConfigurationError("an output already exists; pass --overwrite to replace it")
    results, total_pages = [], 0
    for item in items:
        started = time.monotonic()
        row = {"input": item.relative_input,
               "output": None if scan_only else item.relative_output,
               "status": "failed", "error": None, "page_count": None,
               "text_char_count": None, "classification": None,
               "duration_ms": 0, "source_sha256": None}
        try:
            size = item.source.stat().st_size
            if size > MAX_BYTES_PER_DOCUMENT:
                raise ResourceLimitError("input exceeds the 250 MiB file limit")
            row["source_sha256"] = _sha(item.source)
            from .convert import _select_backend
            report = inspect_pdf(_select_backend(backend), str(item.source))
            row.update(page_count=report.page_count,
                       text_char_count=report.text_char_count,
                       classification=report.classification)
            total_pages += report.page_count
            if report.page_count > MAX_PAGES_PER_DOCUMENT:
                raise ResourceLimitError("input exceeds the 250-page document limit")
            if total_pages > MAX_PAGES_PER_RUN:
                raise ResourceLimitError("batch exceeds the 2,000-page run limit")
            if report.classification == "ocr_required":
                raise OcrRequiredError("this PDF appears to require OCR before conversion")
            if scan_only:
                row["status"] = "blank" if report.classification == "blank" else "would_convert"
            else:
                item.destination.parent.mkdir(parents=True, exist_ok=True)
                convert(str(item.source), str(item.destination), dpi=dpi,
                        refine_rounds=refine_rounds, backend=backend,
                        output_profile=output_profile, oracle=oracle,
                        allow_cloud_upload=allow_cloud_upload or None,
                        verbose=verbose)
                row["status"] = "blank" if report.classification == "blank" else "converted"
        except OcrRequiredError as exc:
            row["status"] = "ocr_required"
            row["error"] = {"code": exc.code, "message": exc.message}
        except Exception as exc:
            code, message = _safe_error(exc)
            row["error"] = {"code": code, "message": message}
        finally:
            row["duration_ms"] = int((time.monotonic() - started) * 1000)
            results.append(row)
        if row["status"] in ("failed", "ocr_required") and not continue_on_error:
            for skipped in items[len(results):]:
                results.append({"input": skipped.relative_input,
                                "output": None if scan_only else skipped.relative_output,
                                "status": "skipped", "error": None,
                                "page_count": None, "text_char_count": None,
                                "classification": None, "duration_ms": 0,
                                "source_sha256": None})
            break
    counts = {name: sum(r["status"] == name for r in results)
              for name in ("converted", "would_convert", "ocr_required", "blank", "failed", "skipped")}
    report = {"schema_version": SCHEMA_VERSION,
              "options": {"scan_only": bool(scan_only), "recursive": bool(recursive),
                          "workers": workers, "continue_on_error": bool(continue_on_error),
                          "overwrite": bool(overwrite), "backend": backend,
                          "dpi": dpi, "refine_rounds": refine_rounds,
                          "output_profile": output_profile, "oracle": oracle},
              "counts": counts, "items": results}
    if result_json:
        _write_json(result_json, report)
    return report
