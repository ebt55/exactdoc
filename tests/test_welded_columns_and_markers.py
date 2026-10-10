"""Lines welded across a gutter, a contents row taken for a script, a bullet
that took its item's first line, and a paragraph joined across its own
indent.

WP40. y12_irs_pub15 (IRS Publication 15, 59 pages, two columns set on
independent grids) mapped 1:1 in LibreOffice and Word on 56 of its pages
once its seams were kept; three could not fit:

* p1, the cover: the 31pt title "(Circular E), " shares a baseline with the
  contents row "Introduction ... 12" 62pt to its right, and the next contents
  row sits 14.7pt above the baseline of "Employer's Tax" -- the first was one
  line by the justification exemption, the second a raised "script" of the
  title. Both crossed the cover's columns; the page ran 587pt over.
* p8 and p31: four to six column lines share a baseline with the other
  column's across the gutter at a real space; each is the only crossing at
  its x, so the repeated-gap gutter test never fired.
* p31 again: the 12pt bullets beside 10pt items took each item's first line
  into a paragraph of its own at 13.9pt leading, and a column's last words,
  cut from a welded line, joined the indented paragraph under them with a
  16.95pt leading read off the paragraph gap.
"""
import os
import tempfile
import unittest

from exactdoc.layout import Para, Run
from exactdoc.parse_pdfium import _Char, _absorb_script_rows, _build_lines, \
    _text_size
from exactdoc.model import Line, Span, TextBlock, PageIR
from exactdoc import dialect
from exactdoc.infer import _mergeable

WORDS = ("employers must withhold federal income tax from the wages of each "
         "employee based on the form the employee gives and the tables in "
         "the publication for the payroll period of the wages paid").split()


def _two_column_pdf(path, welded):
    """Two justified-looking columns on independent grids (the right column
    3.0pt lower), 30 lines each. `welded` left-column line indices are moved
    onto the right column's baseline, ending in a real space at the gutter --
    y12 p8/p31's shape, one crossing per x."""
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(path, pagesize=(612, 792))
    for i in range(30):
        y_l = 740.0 - 11.5 * i
        y_r = y_l - 3.0
        words = WORDS[i % 7:i % 7 + 9]
        left = " ".join(words)
        if i in welded:
            y_l = y_r
            left += " "
        t = c.beginText(42, y_l)
        t.setFont("Helvetica", 10)
        t.textOut(left)
        c.drawText(t)
        t = c.beginText(315, y_r)
        t.setFont("Helvetica", 10)
        t.textOut(" ".join(WORDS[(i + 3) % 7:(i + 3) % 7 + 9]))
        c.drawText(t)
    c.save()


def _page_lines(path, page=0):
    from exactdoc.parse_pdfium import parse_pdf
    ir = parse_pdf(path, keep_image_data=False)
    return [ln for b in ir.pages[page].blocks for ln in b.lines]


class AWeldAcrossAStructuralGutterIsCut(unittest.TestCase):
    def test_lone_crossings_split_at_the_columns_channel(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "t.pdf")
            _two_column_pdf(src, welded={4, 17, 25})
            lines = _page_lines(src)
        crossing = [ln.text for ln in lines
                    if ln.bbox[0] < 300 and ln.bbox[2] > 312]
        self.assertEqual(crossing, [])

    def test_a_single_column_page_is_left_alone(self):
        # no column structure: a wide justified gap after a real space stays
        # forgiven (the exemption's own case)
        from reportlab.pdfgen import canvas
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "t.pdf")
            c = canvas.Canvas(src, pagesize=(612, 792))
            for i in range(20):
                t = c.beginText(72, 720 - 14 * i)
                t.setFont("Helvetica", 10)
                if i == 7:
                    t.textOut("stretched ")
                    t.setTextOrigin(72 + 70, 720 - 14 * i)
                    t.textOut("word here and more prose to fill the line")
                else:
                    t.textOut(" ".join(WORDS[i % 9:i % 9 + 12]))
                c.drawText(t)
            c.save()
            lines = _page_lines(src)
        self.assertIn("stretched word here and more prose to fill the line",
                      [ln.text for ln in lines])


def _char(u, x0, x1, baseline, size, gen=False):
    c = _Char()
    c.u = u
    c.x0, c.x1 = x0, x1
    c.y0, c.y1 = baseline - size, baseline + 0.2 * size
    c.ox, c.oy = x0, baseline
    c.size = size
    c.font = "Helvetica-Bold"
    c.flags = 0
    c.color = "#000000"
    c.gen = gen
    return c


def _text(s, x0, baseline, size):
    adv = 0.55 * size
    out = []
    for i, ch in enumerate(s):
        out.append(_char(ch, x0 + i * adv, x0 + (i + 1) * adv, baseline, size))
    return out


class ACoverTitleIsNotItsNeighboursLine(unittest.TestCase):
    def test_a_31pt_title_and_a_10pt_row_on_one_baseline_are_two_lines(self):
        # "(Circular E), " at 31pt, a real space, and "Introduction" at 10pt
        # 62pt to the right: no justification stretches one space 3x
        chars = _text("(Circular E), ", 42.0, 123.1, 31.0)
        chars += _text("Introduction", 315.0, 123.1, 10.0)
        texts = [ln.text for ln in _build_lines(chars)]
        self.assertIn("(Circular E),", texts)
        self.assertIn("Introduction", texts)

    def test_the_same_size_keeps_the_exemption(self):
        chars = _text("Circular ", 42.0, 123.1, 10.0)
        chars += _text("Introduction", 90.0, 123.1, 10.0)
        self.assertEqual([ln.text for ln in _build_lines(chars)],
                         ["Circular Introduction"])

    def test_a_contents_row_beside_a_title_is_not_its_script(self):
        # the 10pt row's baseline 14.7pt above the 31pt title's, inside its em
        # box; 44 glyphs starting 18pt right of the title's last letter
        host = _text("Employer's Tax ", 42.0, 156.1, 31.0)
        row = _text("1. Employer Identification Number (EIN) 13", 315.0,
                    141.4, 10.0)
        # the title's last letter ends at 296.7, as on the cover
        shift = 296.7 - max(c.x1 for c in host if c.u.strip())
        for c in host:
            c.x0 += shift
            c.x1 += shift
            c.ox += shift
        out = _absorb_script_rows([(0, host), (1, row)])
        self.assertEqual(len(out), 2)

    def test_a_long_exponent_set_against_its_base_still_joins(self):
        host = _text("x", 100.0, 300.0, 12.0)
        exp = _text("(a+b+c+d+e+f+g)", host[-1].x1, 296.0, 7.0)
        out = _absorb_script_rows([(0, host), (1, exp)])
        self.assertEqual(len(out), 1)


def _span(text, x0, x1, base, size):
    return Span(text=text, font="Helvetica", size=size, color="#000000",
                bold=False, italic=False, mono=False, serif=False,
                superscript=False, bbox=(x0, base - size, x1, base + 0.2 * size),
                origin=(x0, base))


def _line(spans):
    return Line(spans=spans, bbox=(min(s.bbox[0] for s in spans),
                                   min(s.bbox[1] for s in spans),
                                   max(s.bbox[2] for s in spans),
                                   max(s.bbox[3] for s in spans)))


class ABulletLeavesItsItemWhole(unittest.TestCase):
    def test_a_larger_bullet_does_not_change_the_lines_type_size(self):
        ln = _line([_span("• ", 321.0, 328.0, 341.5, 12.0),
                    _span("You're a monthly schedule depositor", 332.0, 553.9,
                          340.8, 10.0)])
        self.assertEqual(_text_size(ln), 10.0)
        plain = _line([_span("Heading", 42.0, 120.0, 100.0, 14.0),
                       _span(" text", 120.0, 150.0, 100.0, 10.0)])
        self.assertEqual(_text_size(plain), 14.0)

    def test_the_rejoined_row_stays_in_the_items_block(self):
        bullet = TextBlock(lines=[_line([_span("•", 321.0, 325.7, 341.5, 12.0)])],
                           bbox=(321.0, 329.5, 325.7, 343.9))
        item_lines = [_line([_span(t, 332.0, 553.9, 340.8 + 11.5 * k, 10.0)])
                      for k, t in enumerate(("You're a monthly schedule",
                                             "and make a payment in accordance",
                                             "payment may be $2,500 or more."))]
        item = TextBlock(lines=item_lines, bbox=(332.0, 330.8, 553.9, 366.8))
        page = PageIR(number=1, width=612.0, height=792.0,
                      blocks=[bullet, item])
        dialect._coalesce_row_fragments(page)
        self.assertEqual(len(page.blocks), 1)
        texts = [ln.text for ln in page.blocks[0].lines]
        self.assertEqual(len(texts), 3)
        self.assertTrue(texts[0].startswith("•"))


def _para(text, bbox, first_indent=0.0, align="left"):
    p = Para(runs=[Run(text=text, font="Helvetica", size=10.0,
                       color="#000000")], align=align, bbox=bbox)
    p.first_indent = first_indent
    return p


class AnIndentedParagraphOpensItself(unittest.TestCase):
    def test_a_fragment_does_not_join_the_indented_paragraph_below(self):
        a = _para("the same wording.", (315.0, 52.5, 395.7, 66.7))
        b = _para("If a substitute for Form W-2 is given ...",
                  (315.0, 69.4, 570.0, 164.2), first_indent=12.0)
        self.assertFalse(_mergeable(a, b, 315.0, 570.0))

    def test_a_flush_continuation_still_joins(self):
        a = _para("the same wording", (315.0, 52.5, 395.7, 66.7))
        b = _para("continues here at the margin of its column ...",
                  (315.0, 69.4, 570.0, 164.2))
        self.assertTrue(_mergeable(a, b, 315.0, 570.0))


class AChecklistKeepsItsRows(unittest.TestCase):
    """y12 p8: two checklists side by side, every row "☐ label . . . . N"."""

    def test_a_page_number_closing_a_leader_row_is_not_a_marker(self):
        from exactdoc.infer import _merge_list_markers
        entry = _line([_span("Verify work eligibility ", 64.3, 200.0, 120.9, 9.0),
                       _span(".  .  .  .  .  .  .", 200.0, 256.2, 120.9, 7.2)])
        num = _line([_span("7", 278.3, 283.3, 120.9, 9.0)])
        other = _line([_span("File Form 943 if required", 329.7, 509.4, 121.1, 9.0)])
        blocks = [TextBlock(lines=[entry], bbox=entry.bbox),
                  TextBlock(lines=[num], bbox=num.bbox),
                  TextBlock(lines=[other], bbox=other.bbox)]
        out = _merge_list_markers(blocks)
        texts = sorted(ln.text for b in out for ln in b.lines)
        self.assertIn("7", texts)
        self.assertIn("File Form 943 if required", texts)

    def test_a_step_number_still_glues_to_its_item(self):
        from exactdoc.infer import _merge_list_markers
        num = _line([_span("2", 72.0, 77.0, 200.0, 10.0)])
        item = _line([_span("Mark the bay positions", 90.0, 200.0, 200.0, 10.0)])
        out = _merge_list_markers([TextBlock(lines=[num], bbox=num.bbox),
                                   TextBlock(lines=[item], bbox=item.bbox)])
        self.assertEqual([ln.text for b in out for ln in b.lines],
                         ["2Mark the bay positions"])

    def test_a_checkbox_is_one_marker(self):
        from exactdoc.model import DrawCmd
        white = DrawCmd(kind="fill", shape="rect", bbox=(46.4, 114.6, 52.6, 120.8),
                        fill="#ffffff", stroke=None, width=0.0, opacity=1.0,
                        n_items=5)
        outline = DrawCmd(kind="stroke", shape="complex",
                          bbox=(46.4, 114.6, 52.6, 120.8), fill=None,
                          stroke="#231f20", width=0.5, opacity=1.0, n_items=9)
        self.assertEqual(dialect._drop_knockouts([white, outline]), [outline])
        # a paper-coloured mark alone keeps its reading
        self.assertEqual(dialect._drop_knockouts([white]), [white])


class AFramedPictureLiesOnItsCell(unittest.TestCase):
    def test_a_picture_inside_a_frame_table_floats_without_wrap(self):
        from exactdoc.infer import _float_backgrounds
        from exactdoc.layout import DocLayout, ImageEl, TableEl
        lay = DocLayout()
        lay.margin_l, lay.margin_r, lay.margin_t, lay.margin_b = 42.0, 42.0, 26.7, 29.6
        img = ImageEl(data=b"x", ext="png", width=252.0, height=336.0)
        img._bbox = (43.0, 355.6, 295.0, 691.5)
        frame = TableEl(bbox=(42.0, 353.9, 296.0, 741.0))
        # the contents column beside it and the box line under it: what the
        # wrap test reads as text wrapped round the picture
        beside = [_line([_span("Contents row %d" % k, 315.0, 570.0, 370.0 + 19 * k, 10.0)])
                  for k in range(12)]
        under = _line([_span("Get forms and other information", 49.0, 229.9, 704.0, 9.0)])
        blocks = [TextBlock(lines=beside + [under], bbox=(49.0, 360.0, 570.0, 710.0))]
        keep, floats = _float_backgrounds([frame, img], blocks, lay, 612.0, 792.0)
        self.assertEqual(keep, [frame])
        self.assertEqual(len(floats), 1)
        self.assertIsNone(floats[0].wrap)
        self.assertFalse(floats[0].behind)


if __name__ == "__main__":
    unittest.main()
