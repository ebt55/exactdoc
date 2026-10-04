"""Probe set for the Google Docs numbering/footnotes capability decision.

    python testkit/gdocs_probe_lists_notes.py --out DIR

The gdocs output profile writes lists and footnotes TYPED
(`exactdoc.options.PROFILE_CAPABILITIES`) because LibreOffice does not predict
the Docs importer: a list-indent normalisation proven in LibreOffice regressed
live Docs dx to 63.65pt (2026-08-04). Flipping the capability needs live
evidence, and this script makes it: five small synthetic PDFs, each converted
by the gdocs profile twice -- typed, as it ships, and with the capability
forced on, which is exactly what flipping the switch would produce -- plus the
standard profile's real form for reference. Nothing here uploads anything;
the live pass is a separate, consented step.

What to read off a live render of each pair (word boxes from Docs' exported
PDF against the source PDF, as testkit/gdocs_oracle.py measures them):

  probe_bullets       3-level bullets (•, –, ·), wrapped items: marker x and
                      item-text x per level, wrap indent of line 2.
  probe_decimal       "1." … "3." interrupted by a paragraph and continued
                      ("4."), then "(a)"/"(b)" and "i."/"ii." lists: the
                      printed numbers must equal the source's.
  probe_nested        decimal items with bullet sub-items, and justified
                      "1. text" items (space separator, w:suff nothing).
  probe_footnotes     two pages of continuously numbered notes under a rule:
                      reference glyph position, note position and numbering.
  probe_footnote_marks  a symbol mark ("*") and a numbering restart, which
                      become custom marks.

A manifest.json beside the files lists them and what each tests.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

W, H = 612, 792


def _canvas(path):
    from reportlab.pdfgen import canvas
    return canvas.Canvas(path, pagesize=(W, H))


def _lines(c, items, y, size=11):
    """items: (x, text) or (x, text, font, size)."""
    for it in items:
        x, text = it[0], it[1]
        font = it[2] if len(it) > 2 else "Helvetica"
        sz = it[3] if len(it) > 3 else size
        if text:
            c.setFont(font, sz)
            c.drawString(x, H - y, text)
        if len(it) < 5:
            y += 15
    return y


def probe_bullets(path):
    c = _canvas(path)
    y = _lines(c, [(72, "Bulleted list, three levels", "Helvetica-Bold", 13)], 80)
    y += 6
    # Glyphs from the base-14 WinAnsi set only: a "◦" or "▪" drawn in
    # Helvetica is a missing-glyph box in the source itself.
    rows = [(0, "•", "Site preparation, including the hoarding line and the"),
            (None, None, "boundary photographs taken before any plant arrives"),
            (1, "–", "Confirm the hoarding line against the approved drawing"),
            (2, "·", "Both photographs are retained for the duration"),
            (1, "–", "Isolate the disused feeder at the substation"),
            (0, "•", "Handover to the operator")]
    for lvl, mk, text in rows:
        if lvl is None:
            c.setFont("Helvetica", 11)
            c.drawString(90, H - y, text)
        else:
            c.setFont("Helvetica", 11)
            c.drawString(72 + 18 * lvl, H - y, mk)
            c.drawString(90 + 18 * lvl, H - y, text)
        y += 15
    c.showPage()
    c.save()


def probe_decimal(path):
    c = _canvas(path)
    y = _lines(c, [(72, "Numbered lists", "Helvetica-Bold", 13)], 80) + 6
    for n, t in ((1, "Establish the temporary layover"), (2, "Mark the bay positions"),
                 (3, "Set the stop lines two metres back")):
        _lines(c, [(72, "%d." % n, "Helvetica", 11, 0), (90, t)], y)
        y += 15
    y = _lines(c, [(72, "A paragraph that interrupts the list before it continues.")], y + 4) + 4
    _lines(c, [(72, "4.", "Helvetica", 11, 0), (90, "Publish the revised layover times")], y)
    y += 24
    for mk, t in (("(a)", "the operator's standard"), ("(b)", "the framework rate")):
        _lines(c, [(72, mk, "Helvetica", 11, 0), (96, t)], y)
        y += 15
    y += 9
    for mk, t in (("i.", "first consideration"), ("ii.", "second consideration"),
                  ("iii.", "third consideration")):
        _lines(c, [(72, mk, "Helvetica", 11, 0), (96, t)], y)
        y += 15
    c.showPage()
    c.save()


def probe_nested(path):
    c = _canvas(path)
    y = _lines(c, [(72, "Numbered with bulleted sub-points", "Helvetica-Bold", 13)], 80) + 6
    for n in (1, 2):
        _lines(c, [(72, "%d." % n, "Times-Roman", 11, 0),
                   (90, "Confirm the contingency draw for phase %d" % n, "Times-Roman", 11)], y)
        y += 15
        for t in ("Two relief runs, costed at the framework rate",
                  "No additional vehicles are required"):
            _lines(c, [(90, "•", "Times-Roman", 11, 0), (108, t, "Times-Roman", 11)], y)
            y += 15
    y += 12
    # justified typed items: "N. text" in one run, wrapped to the measure
    words = ("The recommendation is to proceed with the reporting requirement "
             "attached and to bring a further report to the committee in the "
             "autumn once a full quarter of data is available").split()
    for n in (1, 2):
        lines, cur = [], "%d." % n
        for w in words:
            if c.stringWidth(cur + " " + w, "Times-Roman", 11) > 468 - 18:
                lines.append(cur)
                cur = w
            else:
                cur += " " + w
        lines.append(cur)
        for i, ln in enumerate(lines):
            x = 72 if i == 0 else 90
            if i < len(lines) - 1:
                t = c.beginText(x, H - y)
                t.setFont("Times-Roman", 11)
                gaps = ln.count(" ")
                room = (540 - x) - c.stringWidth(ln, "Times-Roman", 11)
                t.setWordSpace(room / gaps if gaps else 0)
                t.textOut(ln)
                c.drawText(t)
            else:
                c.setFont("Times-Roman", 11)
                c.drawString(x, H - y, ln)
            y += 14
        y += 6
    c.showPage()
    c.save()


def _note_page(c, refs, notes, first_line=90):
    y = first_line
    body = ("The committee reviewed the proposal in detail and agreed the "
            "timetable for the depot.")
    for i in range(16):
        c.setFont("Times-Roman", 11)
        c.drawString(72, H - y, body)
        k = i // 5
        if i % 5 == 2 and k < len(refs):
            x = 72 + c.stringWidth(body, "Times-Roman", 11)
            c.setFont("Times-Roman", 7)
            c.drawString(x, H - y + 4, refs[k])
        y += 14
    c.setLineWidth(0.5)
    c.line(72, H - 668, 216, H - 668)
    y = 682
    for n in notes:
        c.setFont("Times-Roman", 6)
        c.drawString(72, H - y + 3, n)
        c.setFont("Times-Roman", 9)
        c.drawString(72 + c.stringWidth(n, "Times-Roman", 6) + 1, H - y,
                     " A note that explains the reference it carries, set in "
                     "smaller type at the foot of the page.")
        y += 11
    c.showPage()


def probe_footnotes(path):
    c = _canvas(path)
    _note_page(c, ["1", "2"], ["1", "2"])
    _note_page(c, ["3"], ["3"])
    c.save()


def probe_footnote_marks(path):
    c = _canvas(path)
    _note_page(c, ["*", "1"], ["*", "1"])
    _note_page(c, ["1"], ["1"])          # a restart: a custom mark
    c.save()


PROBES = [
    ("probe_bullets", probe_bullets, "numbering"),
    ("probe_decimal", probe_decimal, "numbering"),
    ("probe_nested", probe_nested, "numbering"),
    ("probe_footnotes", probe_footnotes, "footnotes"),
    ("probe_footnote_marks", probe_footnote_marks, "footnotes"),
]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    import exactdoc.options as O
    from exactdoc.convert import convert
    gd_caps = O.PROFILE_CAPABILITIES["gdocs"]
    manifest = []
    try:
        for name, make, cap in PROBES:
            pdf = os.path.join(a.out, name + ".pdf")
            make(pdf)
            files = {"source": os.path.basename(pdf)}
            for tag, opts, caps in (
                    ("gdocs-typed", O.PDFIUM_GDOCS_CANDIDATE, gd_caps),
                    ("gdocs-real", O.PDFIUM_GDOCS_CANDIDATE, frozenset({cap})),
                    ("standard", O.RAW, None)):
                if caps is not None:
                    O.PROFILE_CAPABILITIES["gdocs"] = caps
                out = os.path.join(a.out, "%s.%s.docx" % (name, tag))
                convert(pdf, out, options=opts)
                files[tag] = os.path.basename(out)
                O.PROFILE_CAPABILITIES["gdocs"] = gd_caps
            manifest.append({"probe": name, "capability": cap, "files": files})
    finally:
        O.PROFILE_CAPABILITIES["gdocs"] = gd_caps
    with open(os.path.join(a.out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"purpose": "live Google Docs evidence for flipping the gdocs "
                              "numbering/footnotes capability (options.py)",
                   "compare": "gdocs-real vs gdocs-typed vs source, word boxes",
                   "probes": manifest}, f, indent=1)
    for m in manifest:
        print(m["probe"], ", ".join(sorted(m["files"].values())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
