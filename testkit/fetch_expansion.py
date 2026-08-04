"""Fetch real-world PDFs for the expansion corpus, under explicit consent.

    python testkit/fetch_expansion.py --plan testkit/expansion_download_plan.json \
        --out /work/fetch --allow-download

**Nothing is fetched without `--allow-download`.** The flag is per run and is
never implied by the plan file, mirroring `gdocs_oracle.py`'s
`--allow-cloud-upload`: a network action that reaches outside this machine is
opted into at the moment it happens, by the person running it, not by a
configuration file that someone edited a week ago.

This tool does not decide whether a document may be redistributed. It cannot:
that is a judgement about a licence page written for humans. What it does is
refuse to record a document that has no licence and no cited evidence for it, so
the judgement is forced to have been made and written down before the bytes are
committed. `corpus_manifest.verify_expansion()` then rejects `unknown` outright.

The plan carries what we EXPECT; the output carries what we GOT. They are
separate on purpose -- an expectation that silently becomes a record is how a
corpus acquires documents nobody can account for. Every expectation that turns
out wrong (final URL after redirects, size, producer string) is reported as a
divergence and the actual value is what gets written.

Output is a directory of PDFs plus `expansion_provenance.json` in the schema
`corpus_manifest.py expansion-seal` consumes, with `origin: "downloaded"`.
Sealing is a separate, deliberate step -- this tool never writes into
`testkit/fixtures_expansion/`.
"""
import argparse
import datetime
import hashlib
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

import _paths  # noqa: F401

UA = ("exactdoc-corpus/1.0 (PDF->DOCX fidelity test corpus; "
      "one request per document; contact via repository)")
MAX_BYTES = 60 * 1024 * 1024
TIMEOUT = 60
REQUIRED = ("id", "url", "license", "license_evidence", "tier", "why")


def _sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def load_plan(path):
    """-> (entries, problems). A malformed plan never reaches the network."""
    with open(path, encoding="utf-8") as fh:
        plan = json.load(fh)
    entries = plan.get("candidates")
    problems = []
    if not isinstance(entries, list) or not entries:
        return [], [("plan", os.path.basename(path), "no candidates array")]
    seen = set()
    for entry in entries:
        cid = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(entry, dict):
            problems.append(("plan", str(cid), "candidate is not an object"))
            continue
        for field in REQUIRED:
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                problems.append(("plan", str(cid), "missing %s" % field))
        lic = (entry.get("license") or "").strip().lower()
        if lic in ("unknown", "none", "tbd", "n/a"):
            problems.append(("licence", str(cid),
                             "licence %r is not a licence -- an unlicensed file "
                             "does not enter the corpus" % entry.get("license")))
        url = entry.get("url") or ""
        if not url.startswith("https://"):
            problems.append(("transport", str(cid), "url is not https"))
        if not (entry.get("license_evidence") or "").startswith("https://"):
            problems.append(("licence", str(cid),
                             "license_evidence must cite an https page stating "
                             "the terms"))
        if cid in seen:
            problems.append(("plan", str(cid), "duplicate id"))
        seen.add(cid)
        name = entry.get("filename") or ""
        if name and os.path.basename(name) != name:
            problems.append(("plan", str(cid), "filename is not a bare basename"))
    return entries, problems


def _ssl_context():
    """A CA bundle that works off Windows' store as well as on it.

    Measured: `ssl.create_default_context()` on this Windows host failed the ECB
    fetch with CERTIFICATE_VERIFY_FAILED (unable to get local issuer), because
    the Windows certificate store populates intermediates lazily through CryptoAPI
    and Python does not drive that. `certifi` ships the Mozilla bundle and
    resolves the chain the same way on every platform, which is also what a
    reproducible corpus wants. Falls back to the system default when absent --
    a missing optional package should not silently downgrade verification, and
    it does not: verification stays on either way.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def fetch_one(entry, out_dir, retries=1):
    """-> (record, divergences). One request, at most one polite retry.

    A 429 or 503 is answered by honouring `Retry-After` exactly once. There is
    deliberately no general retry loop and no exponential backoff hammering: if
    a host says no twice, the answer is no.

    A 403 is NOT retried and the User-Agent is never disguised. Where that
    status comes from user-agent filtering -- crsreports.congress.gov returned
    it -- the remedy is to fetch the same public-domain work from a host that
    permits automated access, not to make this client look like a browser.
    Dressing up as something else to get past a filter is bot-detection evasion,
    and a corpus is not worth doing that for.
    """
    url = entry["url"]
    request = urllib.request.Request(url, headers={"User-Agent": UA,
                                                    "Accept": "application/pdf"})
    context = _ssl_context()
    try:
        response = urllib.request.urlopen(request, timeout=TIMEOUT, context=context)
    except urllib.error.HTTPError as exc:
        if exc.code not in (429, 503) or retries <= 0:
            raise
        wait = exc.headers.get("Retry-After") if exc.headers else None
        try:
            wait = min(int(wait), 120)
        except (TypeError, ValueError):
            wait = 10
        print("       %s said %d; waiting %ds as instructed, one retry"
              % (url.split("/")[2], exc.code, wait))
        time.sleep(wait)
        return fetch_one(entry, out_dir, retries - 1)
    with response:
        final_url = response.geturl()
        ctype = (response.headers.get("Content-Type") or "").split(";")[0].strip()
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise RuntimeError("larger than the %d byte ceiling" % MAX_BYTES)
    if not data.startswith(b"%PDF-"):
        raise RuntimeError("response is not a PDF (Content-Type %r, first bytes "
                           "%r)" % (ctype, data[:8]))

    name = entry.get("filename") or (entry["id"] + ".pdf")
    path = os.path.join(out_dir, name)
    with open(path, "wb") as fh:
        fh.write(data)

    divergences = []
    if final_url != url:
        divergences.append("redirected to %s" % final_url)
    expected = entry.get("expected_bytes")
    if isinstance(expected, int) and expected and \
            abs(len(data) - expected) > max(expected * 0.5, 200000):
        divergences.append("%d bytes, plan expected about %d" % (len(data), expected))

    producer, pages = _inspect(path)
    if entry.get("expected_producer") and producer and \
            entry["expected_producer"].lower() not in producer.lower():
        divergences.append("producer %r, plan expected %r"
                           % (producer, entry["expected_producer"]))

    record = {
        "filename": name,
        "bytes": len(data),
        "sha256": _sha256_bytes(data),
        "pages": pages,
        "producer": producer,
        "content_type": ctype,
        "final_url": final_url,
    }
    return record, divergences


def _inspect(path):
    """Producer string and page count, via whichever parser is installed."""
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(path)
        try:
            pages = len(doc)
        finally:
            doc.close()
    except Exception:
        pages = None
    try:
        import fitz
        doc = fitz.open(path)
        try:
            return (doc.metadata or {}).get("producer"), pages or doc.page_count
        finally:
            doc.close()
    except Exception:
        return None, pages


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--plan", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--allow-download", action="store_true",
                    help="explicitly authorise THIS run to make network requests")
    ap.add_argument("--only", nargs="*", default=[],
                    help="fetch only these candidate ids")
    a = ap.parse_args(argv)

    entries, problems = load_plan(a.plan)
    if problems:
        print("plan is not usable; no request was made:")
        for kind, cid, why in problems:
            print("  %-9s %-10s %s" % (kind, str(cid)[:10], why))
        return 2
    if a.only:
        entries = [e for e in entries if e["id"] in set(a.only)]
        if not entries:
            print("no candidate matched --only")
            return 2

    if not a.allow_download:
        print("refusing to fetch: --allow-download is required for every run.\n")
        print("This run would make %d request(s) to:" % len(entries))
        hosts = {}
        for e in entries:
            host = e["url"].split("/")[2]
            hosts.setdefault(host, []).append(e["id"])
        for host, ids in sorted(hosts.items()):
            print("  %-34s %s" % (host, ", ".join(sorted(ids))))
        total = sum(e.get("expected_bytes") or 0 for e in entries)
        print("\nabout %.1f MB expected in total." % (total / 1048576.0))
        return 2

    os.makedirs(a.out, exist_ok=True)
    documents, failed = {}, []
    for entry in entries:
        try:
            record, divergences = fetch_one(entry, a.out)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError,
                RuntimeError) as exc:
            failed.append((entry["id"], "%s: %s" % (type(exc).__name__, exc)))
            print("  FAIL %-10s %s" % (entry["id"], exc))
            continue
        documents[record["filename"]] = {
            "tier": entry["tier"],
            "dialect": (record["producer"] or "unknown-producer")[:60],
            "why": entry["why"],
            "provenance": {
                "origin": "downloaded",
                "recipe": None,
                "source_url": record["final_url"],
                "license": entry["license"],
                "license_evidence": entry["license_evidence"],
                "acquired": datetime.date.today().isoformat(),
                "producer": record["producer"],
            },
        }
        print("  OK   %-10s %-34s %7d bytes  %s pages  producer=%s"
              % (entry["id"], record["filename"], record["bytes"],
                 record["pages"], record["producer"]))
        for note in divergences:
            print("       diverged: %s" % note)

    side = os.path.join(a.out, "expansion_provenance.json")
    with open(side, "w", encoding="utf-8") as fh:
        json.dump({"schema": "exactdoc.expansion-provenance.v1",
                   "documents": documents}, fh, indent=1, sort_keys=True)
        fh.write("\n")

    print("\n%d fetched, %d failed. Provenance: %s" % (len(documents), len(failed), side))
    if failed:
        for cid, why in failed:
            print("  %-10s %s" % (cid, why))
    print("\nNOT sealed. Inspect each document, confirm its licence statement "
          "still says what the plan claims, drop anything doubtful, then:\n"
          "  python testkit/corpus_manifest.py expansion-seal %s" % a.out)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
