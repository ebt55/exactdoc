"""Regenerate exactdoc/_base14_widths.py from the published Adobe AFM metrics.

    python testkit/gen_base14_widths.py          # writes exactdoc/_base14_widths.py
    python testkit/gen_base14_widths.py --check  # exit 1 if the file is stale

The committed table is DATA, and data with no generator beside it is data nobody
can re-derive. This is that generator.

**Source, and why this one.** reportlab's `reportlab.pdfbase._fontdata` carries
the Adobe Font Metrics for the 14 standard PostScript faces under BSD-3-Clause.
Those numbers are also in the PDF specification and in every PDF toolkit -- they
are published data, not any one project's property. What matters is that they
are NOT taken from MuPDF: exactdoc is Apache-2.0 precisely because PyMuPDF left
the dependency graph, and copying its tables back in as literals would undo
that. reportlab is a `test`-extra dependency, so this runs in the measurement
environment and its output ships; nothing at runtime needs it.

`tests/test_base14_metrics.py` re-derives the same comparison as an assertion,
so a hand-edit to the generated file fails the suite rather than sitting there.
"""
import argparse
import os
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TARGET = os.path.join(ROOT, "exactdoc", "_base14_widths.py")

# MuPDF shorthand -> PostScript name. The shorthands are what `ladder._b14`
# returns, so the table is keyed the way the caller asks.
SHORT = {"helv": "Helvetica", "hebo": "Helvetica-Bold",
         "heit": "Helvetica-Oblique", "hebi": "Helvetica-BoldOblique",
         "tiro": "Times-Roman", "tibo": "Times-Bold",
         "tiit": "Times-Italic", "tibi": "Times-BoldItalic",
         "cour": "Courier", "cobo": "Courier-Bold"}

VARNAME = {"helv": "_HELVETICA", "hebo": "_HELVETICA_BOLD",
           "tiro": "_TIMES_ROMAN", "tibo": "_TIMES_BOLD",
           "tiit": "_TIMES_ITALIC", "tibi": "_TIMES_BOLD_ITALIC"}

HEADER = '''"""Adobe AFM advance widths for the standard-14 faces, in 1/1000 em.

**Provenance and licence.** These are the published Adobe Font Metrics for the
14 standard PostScript fonts -- the same numbers carried by the PDF
specification and by every PDF toolkit -- taken from reportlab's
`reportlab.pdfbase._fontdata` tables (BSD-3-Clause) and cross-checked glyph by
glyph against a second independent implementation. They are deliberately NOT
copied out of MuPDF: exactdoc is Apache-2.0 because PyMuPDF left the dependency
graph, and lifting its tables back in as literals would undo that. See
docs/license-audit.md.

**Generated, not hand-written**, by `testkit/gen_base14_widths.py`.
`tests/test_base14_metrics.py` re-derives the comparison as an assertion, so an
edit here fails the suite instead of surviving unnoticed.

**Six tables for ten faces**, because the AFM data itself shares them: the
oblique Helvetica faces carry the widths of their upright siblings
(Helvetica-Oblique == Helvetica, Helvetica-BoldOblique == Helvetica-Bold), the
four Times faces are all distinct, and both Courier faces are uniformly 600 --
fixed pitch needs no table at all.

**Keyed on Unicode codepoints, not byte codes.** The AFM is indexed by glyph
name over the WinAnsi repertoire, so the mapping runs through cp1252 once, here,
rather than at every lookup. One consequence is deliberate: WinAnsiEncoding
fills its *unused* byte codes with `bullet`, and 0x7F is one of them, but U+007F
the character is DEL -- so the control range is omitted and DEL takes the
missing-glyph fallback, which is also what MuPDF answers.
"""

#: The advance charged for a codepoint the face has no glyph for: the face's own
#: space width. Not an arbitrary choice -- it is what MuPDF charges, so the two
#: implementations agree on unrepresentable text as well as on text both can see.
FALLBACK = {
%(fallback)s
}
'''

FOOTER = '''
#: Courier is fixed pitch, so every codepoint costs the same whether the face has
#: a glyph for it or not -- which is why `cour`/`cobo` map to None below and need
#: no fallback case.
COURIER_WIDTH = 600

#: The ten shorthand names `ladder._b14` can return -> the table describing each.
WIDTHS = {
    "helv": _HELVETICA,          "heit": _HELVETICA,
    "hebo": _HELVETICA_BOLD,     "hebi": _HELVETICA_BOLD,
    "tiro": _TIMES_ROMAN,        "tibo": _TIMES_BOLD,
    "tiit": _TIMES_ITALIC,       "tibi": _TIMES_BOLD_ITALIC,
    "cour": None,                "cobo": None,
}
'''


def afm_tables():
    """{shorthand: {codepoint: width}} from reportlab's AFM data."""
    from reportlab.pdfbase import _fontdata
    enc = _fontdata.encodings["WinAnsiEncoding"]
    out = {}
    for short, face in SHORT.items():
        widths = _fontdata.widthsByFontGlyph[face]
        row = {}
        for code in range(32, 256):
            gname = enc[code]
            if gname in (None, ".notdef") or gname not in widths:
                continue
            try:
                ch = bytes([code]).decode("cp1252")
            except UnicodeDecodeError:
                continue
            if unicodedata.category(ch) == "Cc":
                continue                       # see the header note on 0x7F
            row[ord(ch)] = int(widths[gname])
        out[short] = row
    return out


def render(tables):
    def fmt(table):
        lines, row = [], []
        for cp in sorted(table):
            row.append("0x%04X: %d," % (cp, table[cp]))
            if len(row) == 8:
                lines.append("    " + " ".join(row))
                row = []
        if row:
            lines.append("    " + " ".join(row))
        return "\n".join(lines)

    fallback = "\n".join('    "%s": %d,' % (s, tables[s][0x20])
                         for s in sorted(tables))
    parts = [HEADER % {"fallback": fallback}]
    for short in ("helv", "hebo", "tiro", "tibo", "tiit", "tibi"):
        parts.append("\n%s = {\n%s\n}\n" % (VARNAME[short], fmt(tables[short])))
    parts.append(FOOTER)
    return "".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="do not write; exit 1 if the committed file is stale")
    a = ap.parse_args(argv)
    try:
        text = render(afm_tables())
    except ImportError:
        print("reportlab is not installed -- this generator needs the `test` "
              "extra: pip install exactdoc[test]")
        return 2

    if a.check:
        with open(TARGET, encoding="utf-8") as fh:
            current = fh.read()
        if current == text:
            print("%s is up to date" % os.path.relpath(TARGET, ROOT))
            return 0
        print("%s DIFFERS from what this generator produces -- it was "
              "hand-edited, or reportlab's AFM data moved."
              % os.path.relpath(TARGET, ROOT))
        return 1

    with open(TARGET, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("wrote %s" % os.path.relpath(TARGET, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
