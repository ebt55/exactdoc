"""Fetch the holdout set: wild PDFs that are NEVER used while developing fixes.

Discipline, not tooling: every corpus document has by now been diagnosed
against -- page images inspected, drift decomposed, thresholds adjusted. Once a
document has shaped a fix it can no longer falsify the converter; scores on it
measure memorisation as much as generalisation. The holdout exists to answer
one question at release time: "did the last month of fixes generalise?"

Rules:
  * run the gate on these, read the SUMMARY NUMBERS ONLY;
  * never open their comparison images or drift tables while developing;
  * a holdout failure is investigated on a NEW document that reproduces it,
    never on the holdout file itself;
  * once a holdout document has been diagnosed against, it is burned --
    replace it and say so in the commit message.

The files are fetched, not committed: they are other people's documents, and
the corpus stays reproducible from URLs.
"""
import os
import sys
import urllib.request

import _paths  # noqa: F401

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "holdout")

# Chosen for producer diversity, not content: two pdfTeX generations, one
# ancient OpenOffice export, one modern TeX with heavy math/tables.
URLS = {
    "h_resnet.pdf": "https://arxiv.org/pdf/1512.03385",           # pdfTeX 1.40.x
    "h_instructgpt.pdf": "https://arxiv.org/pdf/2203.02155",      # pdfTeX, tables
    "h_bitcoin.pdf": "https://bitcoin.org/bitcoin.pdf",           # OpenOffice 2.4
    "h_attention_v1.pdf": "https://arxiv.org/pdf/1706.03762v1",   # older pdfTeX
}


def main():
    os.makedirs(OUT, exist_ok=True)
    ok = 0
    for name, url in URLS.items():
        dst = os.path.join(OUT, name)
        if os.path.exists(dst) and os.path.getsize(dst) > 10000:
            print("  have %-22s" % name)
            ok += 1
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "exactdoc-holdout"})
            with urllib.request.urlopen(req, timeout=120) as r, open(dst, "wb") as f:
                f.write(r.read())
            print("  got  %-22s %8d bytes" % (name, os.path.getsize(dst)))
            ok += 1
        except Exception as e:
            print("  FAIL %-22s %s" % (name, str(e)[:60]))
    print("%d/%d holdout documents present in %s" % (ok, len(URLS), OUT))
    return 0 if ok == len(URLS) else 1


if __name__ == "__main__":
    sys.exit(main())
