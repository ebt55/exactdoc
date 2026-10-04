"""Probe set for the Google Docs `bidi` capability decision (WP14).

    python testkit/gdocs_probe_rtl.py --out DIR

Both profiles declare right-to-left paragraphs (w:bidi, start/end w:jc and
w:ind, w:rtl runs with complex-script size and language); a profile without the
`bidi` capability (`exactdoc.options.PROFILE_CAPABILITIES`) writes the visual
equivalent -- a left-to-right paragraph with the sides swapped. LibreOffice does
not predict Docs, so gdocs got the capability only on live evidence: this
script's set, flown 2026-10-04 (docs/evidence/gdocs-2026-10-04-rtl-probe.json).
Each source is converted by the gdocs profile without the capability
("gdocs-visual") and with it ("gdocs-bidi"), and by the standard profile for
reference. Nothing here uploads
anything; the live pass is a separate, consented step.

What to read off a live render of each pair (word boxes from Docs' exported
PDF against the source PDF, as testkit/gdocs_oracle.py measures them):

  probe_he_justified  a justified Hebrew paragraph, 1.5-line pitch, ragged-LEFT
                      last line, a sentence-final full stop and a
                      parenthesis: line ends and punctuation side.
  probe_he_list       Hebrew items numbered `1.` `2.` and `א.` `ב.`, marker on
                      the right, hanging text: marker x and text x.
  c4_i18n             the gated multilingual page (Arabic and Hebrew lines).
  y48_ar_weasyprint   seven pages of Arabic (WeasyPrint), numbers inside text.
  y49_he_word2016     28 pages of Hebrew (Word 2016) with footnotes.

A manifest.json beside the files lists them.
"""
import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

W, H = 612, 792


def _font():
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
                 r"C:\Windows\Fonts\arial.ttf"):
        if os.path.exists(path):
            return path
    raise SystemExit("no Hebrew-capable TrueType font found")


def _canvas(path):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
    pdfmetrics.registerFont(TTFont("HebProbe", _font()))
    return canvas.Canvas(path, pagesize=(W, H)), pdfmetrics


def _draw_rtl_line(c, pm, words, y, x_right, x_left, justify, size=11):
    """Words placed right to left, each drawn in visual order (as Word does)."""
    sw = pm.stringWidth(" ", "HebProbe", size)
    widths = [pm.stringWidth(w, "HebProbe", size) for w in words]
    extra = 0.0
    if justify and len(words) > 1:
        extra = ((x_right - x_left) - sum(widths) - sw * (len(words) - 1)) \
            / (len(words) - 1)
    x = x_right
    for w, wd in zip(words, widths):
        c.drawString(x - wd, H - y, w[::-1].translate(str.maketrans("()", ")(")))
        x -= wd + sw + extra


def probe_he_justified(path):
    c, pm = _canvas(path)
    c.setFont("HebProbe", 11)
    text = ("איכות האחזור יורדת באופן לא ליניארי ככל שהקורפוס גדל מעבר לנקודה "
            "שבה כויל מודל ההטמעה (ראו להלן), והצוות לא רואה זאת כי הוא מודד "
            "רק ממוצעים של רלוונטיות בכל הרבעונים של השנה האחרונה.")
    y = 90.0
    for para in range(2):
        words, i = text.split(), 0
        while i < len(words):
            line, wsum = [], 0.0
            while i < len(words):
                w = pm.stringWidth(words[i], "HebProbe", 11)
                sw = pm.stringWidth(" ", "HebProbe", 11)
                if line and wsum + sw + w > 468:
                    break
                line.append(words[i])
                wsum += w + (sw if len(line) > 1 else 0)
                i += 1
            _draw_rtl_line(c, pm, line, y, 540, 72, justify=i < len(words))
            y += 16.5
    c.showPage()
    c.save()


def probe_he_list(path):
    c, pm = _canvas(path)
    c.setFont("HebProbe", 11)
    items = [("1.", "מבוא: על הצורך בדיון בהיבטים מתודולוגיים"),
             ("2.", "תהליך התאמת כלי התצפית למחקר"),
             ("א.", "מה יהיה אתר התצפית"),
             ("ב.", "מה תהיה יחידת התצפית")]
    y = 90.0
    for mk, t in items:
        c.drawString(540 - pm.stringWidth(mk, "HebProbe", 11), H - y,
                     mk[::-1])
        _draw_rtl_line(c, pm, t.split(), y, 516, 72, justify=False)
        y += 16.0
    c.showPage()
    c.save()


SYNTH = [("probe_he_justified", probe_he_justified),
         ("probe_he_list", probe_he_list)]
FIXTURES = [("c4_i18n", os.path.join(ROOT, "testkit", "fixtures", "c4_i18n.pdf")),
            ("y48_ar_weasyprint", os.path.join(ROOT, "testkit", "fixtures_expansion",
                                               "y48_ar_weasyprint.pdf")),
            ("y49_he_word2016", os.path.join(ROOT, "testkit", "fixtures_expansion",
                                             "y49_he_word2016.pdf"))]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    import exactdoc.options as O
    from exactdoc.convert import convert
    gd_caps = O.PROFILE_CAPABILITIES["gdocs"]
    sources = []
    for name, make in SYNTH:
        pdf = os.path.join(a.out, name + ".pdf")
        make(pdf)
        sources.append((name, pdf))
    for name, path in FIXTURES:
        if os.path.exists(path):
            dst = os.path.join(a.out, name + ".pdf")
            shutil.copyfile(path, dst)
            sources.append((name, dst))
    manifest = []
    try:
        for name, pdf in sources:
            files = {"source": os.path.basename(pdf)}
            for tag, opts, caps in (
                    ("gdocs-visual", O.PDFIUM_GDOCS_CANDIDATE, gd_caps - {"bidi"}),
                    ("gdocs-bidi", O.PDFIUM_GDOCS_CANDIDATE, gd_caps | {"bidi"}),
                    ("standard", O.RAW, None)):
                if caps is not None:
                    O.PROFILE_CAPABILITIES["gdocs"] = frozenset(caps)
                out = os.path.join(a.out, "%s.%s.docx" % (name, tag))
                convert(pdf, out, options=opts)
                files[tag] = os.path.basename(out)
                O.PROFILE_CAPABILITIES["gdocs"] = gd_caps
            manifest.append({"probe": name, "capability": "bidi", "files": files})
    finally:
        O.PROFILE_CAPABILITIES["gdocs"] = gd_caps
    with open(os.path.join(a.out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"purpose": "live Google Docs evidence for flipping the gdocs "
                              "bidi capability (options.py)",
                   "compare": "gdocs-bidi vs gdocs-visual vs source, word boxes "
                              "and line ends; punctuation side on RTL lines",
                   "probes": manifest}, f, indent=1)
    for m in manifest:
        print(m["probe"], ", ".join(sorted(m["files"].values())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
