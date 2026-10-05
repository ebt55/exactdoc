"""Probe set for the Google Docs `anchor_pictures` capability decision (WP24).

    python testkit/gdocs_probe_anchors.py --out DIR [--corpus y01_nist_sp80063b ...]

The standard profile anchors a picture set on a text line, wrapped by a
paragraph or printed into a margin at its source position (WP23:
`infer._on_text_line`, `_wrapped_by_text`; wp:anchor, wrapSquare where the
source wrapped); the gdocs profile stacked it in the flow under its line.
Stacked, such a picture costs its own height: SP 800-63B's contents numbers
(y01) ran at a 32pt pitch in Docs for the source's 20, DOE OIG's highlights
picture (y28) took a page of its own. LibreOffice does not predict Docs, so
the capability was decided live: each source converted by the gdocs profile
without it ("<stem>.wp24.gdocs.docx") and with it ("<stem>.wp24a.gdocs.docx").
Flown 2026-10-06 (docs/evidence/gdocs-2026-10-06-wp24-live.json): Docs keeps
the anchors (this set 6 -> 5 pages, y01 81 -> 80, y28 22 -> 21), and gdocs
has the capability since. Nothing here uploads anything.

The synthetic document, five pages, each full enough that a stacked picture
spills it (so the page count alone answers "honoured"), every line carrying a
marker word ANC<page>L<nn> for its position:

  page 1  a contents page: 22 entries whose numbers are 17x10pt pictures set
          on the entry's line (y01's class).
  page 2  a 72pt icon with the first six lines of a paragraph wrapped beside
          it, the rest running under it (SP 800-63B's authenticator icons).
  page 3  a 320x390pt picture beside a text column, running off the paper's
          foot (y28's highlights page).
  page 4  a 20pt logo beside the last line, "Date updated" (NIST's
          withdrawal notice).
  page 5  control: a figure with its caption under it, beside nothing. It
          stays in the flow in both forms and must not move.

What to read off a live render (word boxes from Docs' exported PDF against the
source, as the oracle measures them): pages (5 = honoured), each marker's dy,
and where each picture landed (its image box against the source's).

A manifest.json beside the files lists them.
"""
import argparse
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

W, H = 612, 792
STEM = "probe_anchors"


def _png(w, h, rgb):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (max(4, int(w * 2)), max(4, int(h * 2))), rgb)
    d = ImageDraw.Draw(im)
    d.rectangle([1, 1, im.size[0] - 2, im.size[1] - 2], outline=(20, 20, 20))
    b = io.BytesIO()
    im.save(b, "PNG")
    b.seek(0)
    return b


def _image(c, x, y_top, w, h, rgb):
    from reportlab.lib.utils import ImageReader
    c.drawImage(ImageReader(_png(w, h, rgb)), x, H - y_top - h, w, h)


def _text(c, x, y_base, s, size=11, font="Times-Roman"):
    c.setFont(font, size)
    c.drawString(x, H - y_base, s)


FILL = ("assurance levels bind the claimant to an authenticator through a "
        "protocol that the verifier controls end to end").split()


def _words(k, n):
    return " ".join(FILL[(k + i) % len(FILL)] for i in range(n))


def make_pdf(path):
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(path, pagesize=(W, H))
    # 1: contents numbers drawn as pictures on their lines
    _text(c, 72, 90, "ANC1L00 Table of Contents", 16, "Helvetica-Bold")
    for i in range(22):
        y = 125 + i * 28
        _image(c, 72, y - 9, 17, 10, (40, 70, 140))
        _text(c, 96, y, "ANC1L%02d %s %s" % (i + 1, _words(i, 5), "." * 20 + " %d" % (i + 3)))
    c.showPage()
    # 2: a paragraph wrapped round an icon, then under it
    _text(c, 72, 90, "ANC2L00 Authenticator types", 16, "Helvetica-Bold")
    _image(c, 72, 108, 72, 72, (200, 120, 40))
    y = 118
    for i in range(40):
        x = 153 if y < 108 + 72 + 4 else 72
        n = 9 if x == 153 else 11
        _text(c, x, y, "ANC2L%02d %s" % (i + 1, _words(i, n)))
        y += 15.5
    c.showPage()
    # 3: a picture beside a column, off the paper's foot
    _text(c, 72, 90, "ANC3L00 Highlights", 16, "Helvetica-Bold")
    _image(c, 291, 435, 320, 390, (60, 150, 90))
    y = 120
    for i in range(40):
        _text(c, 72, y, "ANC3L%02d %s" % (i + 1, _words(i, 4)), 10)
        y += 15.0
    c.showPage()
    # 4: a logo beside the last line
    _text(c, 72, 90, "ANC4L00 Withdrawal notice", 16, "Helvetica-Bold")
    y = 120
    for i in range(38):
        _text(c, 72, y, "ANC4L%02d %s" % (i + 1, _words(i, 7)))
        y += 15.5
    _image(c, 420, y - 15, 20, 20, (150, 40, 40))
    _text(c, 72, y, "ANC4L99 Date updated: October 6, 2026")
    c.showPage()
    # 5: control -- a figure and its caption, beside nothing
    _text(c, 72, 90, "ANC5L00 A figure in the flow", 16, "Helvetica-Bold")
    y = 120
    for i in range(10):
        _text(c, 72, y, "ANC5L%02d %s" % (i + 1, _words(i, 11)))
        y += 15.5
    _image(c, 206, y + 10, 200, 120, (90, 90, 160))
    y += 150
    _text(c, 220, y, "ANC5L50 Figure 1: a picture beside nothing", 9)
    y += 24
    for i in range(12):
        _text(c, 72, y, "ANC5L%02d %s" % (i + 60, _words(i, 11)))
        y += 15.5
    c.showPage()
    c.save()


def convert_pair(src, out_dir, stem):
    """Write <stem>.wp24.gdocs.docx (stacked: the capability withdrawn) and
    <stem>.wp24a.gdocs.docx (granted), whatever the profile now carries."""
    from exactdoc import options
    from exactdoc.convert import convert
    from exactdoc.options import PDFIUM_GDOCS_CANDIDATE
    out = {}
    for tag, grant in (("wp24", False), ("wp24a", True)):
        dst = os.path.join(out_dir, "%s.%s.gdocs.docx" % (stem, tag))
        saved = options.PROFILE_CAPABILITIES["gdocs"]
        options.PROFILE_CAPABILITIES["gdocs"] = (saved | {"anchor_pictures"}) if grant \
            else (saved - {"anchor_pictures"})
        try:
            convert(src, dst, options=PDFIUM_GDOCS_CANDIDATE)
        finally:
            options.PROFILE_CAPABILITIES["gdocs"] = saved
        out[tag] = os.path.basename(dst)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--corpus", nargs="*", default=["y01_nist_sp80063b",
                                                   "y28_doe_oig_word365"])
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    src = os.path.join(a.out, STEM + ".pdf")
    make_pdf(src)
    manifest = {STEM: dict(src=os.path.basename(src), **convert_pair(src, a.out, STEM))}
    for stem in a.corpus:
        pdf = None
        for sub in ("fixtures_expansion", "fixtures"):
            p = os.path.join(HERE, sub, stem + ".pdf")
            if os.path.exists(p):
                pdf = p
        if pdf is None:
            raise SystemExit("no such document: " + stem)
        manifest[stem] = dict(src=os.path.relpath(pdf, ROOT).replace(os.sep, "/"),
                              **convert_pair(pdf, a.out, stem))
    with open(os.path.join(a.out, "anchors_manifest.json"), "w", newline="\n") as f:
        json.dump(manifest, f, indent=1)
        f.write("\n")
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
