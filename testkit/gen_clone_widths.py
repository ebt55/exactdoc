"""Regenerate exactdoc/_clone_widths.py from the Carlito and Caladea font files.

    python testkit/gen_clone_widths.py --fonts DIR          # writes the module
    python testkit/gen_clone_widths.py --fonts DIR --check  # exit 1 if stale

The ladder and the writer's page predictions shape text in the family the
DOCX names. For Calibri they used Helvetica's widths (`ladder._B14` mapped
"carlito" onto the base-14 Helvetica faces), which are 8.6% wider at regular
weight and 14.7% wider at bold -- so every `predict_lines` on a Calibri
document (NIST SP 800-171r2 is 82% Calibri) over-predicted its lines. This
generator produces the real tables.

**Source, and why this one.** Carlito (SIL Open Font License 1.1) and Caladea
(Apache License 2.0) are Google's metric-compatible replacements for Calibri
and Cambria: drawn on the same advance widths so documents re-wrap
identically. The tables are read from THOSE files, never from Microsoft's,
and the module records each source file's SHA-256 so the provenance can be
re-checked. Checked against the Microsoft faces where both were installed
(Windows 11, 2026-10-04), over the WinAnsi repertoire: Carlito equals Calibri
on 215 of 216 codepoints (the exception is U+0192, which nobody's body text
carries); Caladea, drawn at 1000 units against Cambria's 2048, equals it to
within that rounding.

**The repertoire is WinAnsi**, the same as `_base14_widths.py`, because
`ladder._measurable` gates every shaped character on cp1252 -- a wider table
would carry numbers no caller is allowed to use.

The font files are read with a few lines of `struct` (head, hhea, hmtx and a
format-4 cmap), so the generator needs nothing installed. `--fonts` names a
directory holding Carlito-{Regular,Bold,Italic,BoldItalic}.ttf and the four
Caladea files; on Windows, C:/Windows/Fonts has them when LibreOffice's font
pack is installed, and on Debian/Ubuntu they ship as fonts-crosextra-carlito
and fonts-crosextra-caladea.
"""
import argparse
import hashlib
import os
import struct
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TARGET = os.path.join(ROOT, "exactdoc", "_clone_widths.py")

#: face key (what `ladder._face` returns) -> source file name
FACES = {
    "carlito": "Carlito-Regular.ttf", "carlito-b": "Carlito-Bold.ttf",
    "carlito-i": "Carlito-Italic.ttf", "carlito-bi": "Carlito-BoldItalic.ttf",
    "caladea": "Caladea-Regular.ttf", "caladea-b": "Caladea-Bold.ttf",
    "caladea-i": "Caladea-Italic.ttf", "caladea-bi": "Caladea-BoldItalic.ttf",
}

DEFAULT_DIRS = ("C:/Windows/Fonts", "/usr/share/fonts/truetype/crosextra",
                "/usr/share/fonts/truetype/carlito",
                "/usr/share/fonts/truetype/caladea")


def _tables(data):
    num = struct.unpack(">H", data[4:6])[0]
    out = {}
    for i in range(num):
        tag, _, off, ln = struct.unpack(">4sIII", data[12 + 16 * i:28 + 16 * i])
        out[tag.decode("latin-1")] = data[off:off + ln]
    return out


def _cmap(tab):
    """codepoint -> glyph id, from the Windows Unicode BMP (format 4) subtable."""
    n = struct.unpack(">H", tab[2:4])[0]
    for i in range(n):
        pid, eid, off = struct.unpack(">HHI", tab[4 + 8 * i:12 + 8 * i])
        if (pid, eid) not in ((3, 1), (0, 3)):
            continue
        sub = tab[off:]
        if struct.unpack(">H", sub[0:2])[0] != 4:
            continue
        segx2 = struct.unpack(">H", sub[6:8])[0]
        seg = segx2 // 2
        ends = struct.unpack(">%dH" % seg, sub[14:14 + segx2])
        starts = struct.unpack(">%dH" % seg, sub[16 + segx2:16 + 2 * segx2])
        deltas = struct.unpack(">%dh" % seg, sub[16 + 2 * segx2:16 + 3 * segx2])
        ro_off = 16 + 3 * segx2
        ranges = struct.unpack(">%dH" % seg, sub[ro_off:ro_off + segx2])
        out = {}
        for s in range(seg):
            for cp in range(starts[s], ends[s] + 1):
                if cp == 0xFFFF:
                    continue
                if ranges[s] == 0:
                    gid = (cp + deltas[s]) & 0xFFFF
                else:
                    p = ro_off + 2 * s + ranges[s] + 2 * (cp - starts[s])
                    gid = struct.unpack(">H", sub[p:p + 2])[0]
                    if gid:
                        gid = (gid + deltas[s]) & 0xFFFF
                if gid:
                    out[cp] = gid
        return out
    raise ValueError("no format-4 Unicode cmap")


def read_face(path):
    """(units_per_em, {codepoint: advance in font units}) over WinAnsi."""
    with open(path, "rb") as fh:
        data = fh.read()
    t = _tables(data)
    upm = struct.unpack(">H", t["head"][18:20])[0]
    nhm = struct.unpack(">H", t["hhea"][34:36])[0]
    hmtx = t["hmtx"]
    adv = [struct.unpack(">H", hmtx[4 * i:4 * i + 2])[0] for i in range(nhm)]
    cmap = _cmap(t["cmap"])
    row = {}
    for code in range(32, 256):
        try:
            ch = bytes([code]).decode("cp1252")
        except UnicodeDecodeError:
            continue
        if unicodedata.category(ch) == "Cc":
            continue                 # as in gen_base14_widths: DEL is not a glyph
        gid = cmap.get(ord(ch))
        if gid is None:
            continue
        row[ord(ch)] = adv[min(gid, nhm - 1)]
    return upm, row, hashlib.sha256(data).hexdigest()


HEADER = '''"""Advance widths of Carlito and Caladea, the metric clones of Calibri and Cambria.

**Generated, not hand-written**, by `testkit/gen_clone_widths.py` from the font
files named below (Carlito: SIL Open Font License 1.1; Caladea: Apache License
2.0). `tests/test_clone_metrics.py` re-runs the generator wherever the files are
installed and fails on any difference.

Values are in each face's own font units (`UNITS_PER_EM`), keyed on Unicode
codepoints over the WinAnsi repertoire -- the same domain as
`_base14_widths.py`, because `ladder._measurable` admits nothing else.

Why these two faces: the standard profile writes Calibri and Cambria by name
and LibreOffice substitutes these clones for them; both pairs share advance
widths by design (checked glyph by glyph -- see the generator's docstring), so
one table measures what Word, LibreOffice-with-the-clones and Google Docs'
Carlito all lay out. Before this table the ladder shaped Calibri with
Helvetica's widths, 8.6%% too wide at regular weight and 14.7%% at bold.
"""

#: Source file of each table and its SHA-256, for re-deriving the numbers.
SOURCES = {
%(sources)s
}

#: Font units per em, per face.
UNITS_PER_EM = {
%(upm)s
}

#: The advance charged for a codepoint the face has no glyph for: its own space
#: width, the same rule `_base14_widths.FALLBACK` follows.
FALLBACK = {
%(fallback)s
}
'''


def render(faces):
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

    parts = [HEADER % {
        "sources": "\n".join('    "%s": ("%s", "%s"),' % (k, FACES[k], faces[k][2])
                             for k in sorted(faces)),
        "upm": "\n".join('    "%s": %d,' % (k, faces[k][0]) for k in sorted(faces)),
        "fallback": "\n".join('    "%s": %d,' % (k, faces[k][1][0x20])
                              for k in sorted(faces)),
    }]
    for k in sorted(faces):
        parts.append("\n_%s = {\n%s\n}\n" % (k.upper().replace("-", "_"),
                                             fmt(faces[k][1])))
    parts.append("\n#: face key -> its table.\nWIDTHS = {\n%s\n}\n" % "\n".join(
        '    "%s": _%s,' % (k, k.upper().replace("-", "_")) for k in sorted(faces)))
    return "".join(parts)


def find_dir(explicit=None):
    for d in ([explicit] if explicit else []) + list(DEFAULT_DIRS):
        if d and all(os.path.exists(os.path.join(d, f)) for f in FACES.values()):
            return d
    return None


def faces_from(directory):
    return {k: read_face(os.path.join(directory, f)) for k, f in FACES.items()}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fonts", default=None,
                    help="directory holding the Carlito and Caladea .ttf files")
    ap.add_argument("--check", action="store_true",
                    help="do not write; exit 1 if the committed file is stale")
    a = ap.parse_args(argv)
    d = find_dir(a.fonts)
    if d is None:
        print("Carlito/Caladea font files not found (tried %s)"
              % ", ".join(([a.fonts] if a.fonts else []) + list(DEFAULT_DIRS)))
        return 2
    text = render(faces_from(d))
    if a.check:
        with open(TARGET, encoding="utf-8") as fh:
            current = fh.read()
        if current == text:
            print("%s is up to date" % os.path.relpath(TARGET, ROOT))
            return 0
        print("%s DIFFERS from what this generator produces from %s"
              % (os.path.relpath(TARGET, ROOT), d))
        return 1
    with open(TARGET, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("wrote %s from %s" % (os.path.relpath(TARGET, ROOT), d))
    return 0


if __name__ == "__main__":
    sys.exit(main())
