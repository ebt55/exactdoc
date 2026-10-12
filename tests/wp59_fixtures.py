"""Synthetic PDFs for WP59: resume layouts (holdout-2's failures).

Each builder draws the smallest page that shows one mechanism the way a word
processor lays it out, beside a control the converter must keep as it is.
Generated at test time with reportlab and parsed by the real PDFium backend.

R1  page colour     Word's Design > Page Color: one fill over the whole sheet
                    of every page, under a page border (four rules with corner
                    joints). Variants: on every page; on every page but a
                    cover; a page-1-only cover (control); a single full-bleed
                    page (control); page colour under a real header strip; a
                    dark page colour with white text.
R2  two-sided list  right-tab dates beside entries, plus a skills list set
                    flush right beside a coursework list at the margin -- a
                    run of right-aligned lines, each beside a short left line.
                    Control: a right-aligned pull quote beside prose
                    (wp49_fixtures.right_aligned_sidebar).
R3a left-tab fields place and dates set at a LEFT tab: every field starts at
                    one x and ends ragged, beside a label at the margin.
                    Controls: a contents page with left-aligned page numbers,
                    two-column prose whose paragraphs end in short lines.
"""
try:
    from reportlab.pdfgen import canvas as _canvas
    from reportlab.pdfbase.pdfmetrics import stringWidth
except ImportError:                                    # pragma: no cover
    _canvas = None
    stringWidth = None

W, H = 612.0, 792.0
L_MARGIN, R_EDGE = 72.0, 540.0


def available():
    return _canvas is not None


def _y(top):
    return H - top


def _rgb(hexcol):
    return tuple(int(hexcol[i:i + 2], 16) / 255.0 for i in (1, 3, 5))


# --------------------------------------------------------------------- R1
def _sheet(c, colour):
    c.setFillColorRGB(*_rgb(colour))
    c.rect(0, 0, W, H, fill=1, stroke=0)


def _page_border(c, colour="#ff0000", inset=24.0, t=1.4):
    """Word's page border: four filled rules and a square at each corner."""
    c.setFillColorRGB(*_rgb(colour))
    x0, y0, x1, y1 = inset, inset, W - inset, H - inset
    c.rect(x0 + t, y1 - t, x1 - x0 - 2 * t, t, fill=1, stroke=0)    # top
    c.rect(x0 + t, y0, x1 - x0 - 2 * t, t, fill=1, stroke=0)        # bottom
    c.rect(x0, y0 + t, t, y1 - y0 - 2 * t, fill=1, stroke=0)        # left
    c.rect(x1 - t, y0 + t, t, y1 - y0 - 2 * t, fill=1, stroke=0)    # right
    for cx, cy in ((x0, y0), (x1 - t, y0), (x0, y1 - t), (x1 - t, y1 - t)):
        c.rect(cx, cy, t, t, fill=1, stroke=0)


RESUME_TEXT = [
    ("Jane A. Jones", "Times-Bold", 12, "center"),
    ("Cincinnati, OH", "Times-Roman", 10, "center"),
    ("Home: 513-123-4567", "Times-Roman", 10, "center"),
    ("WORK EXPERIENCE", "Times-Bold", 11, "left"),
    ("Internal Revenue Service, Covington, KY", "Times-Bold", 10, "left"),
    ("Examined and audited individual, business and corporate tax returns.", "Times-Roman", 10, "left"),
    ("Conducted field examinations and discussed findings with the taxpayer.", "Times-Roman", 10, "left"),
    ("Performed package audits to ensure compliance with the regulations.", "Times-Roman", 10, "left"),
]


def _resume_page(c, page_no, text_colour=(0, 0, 0)):
    c.setFillColorRGB(*text_colour)
    top = 80.0
    for k in range(3):
        for t, font, size, align in RESUME_TEXT:
            if align == "center" and k:
                continue              # the name block heads the page once
            c.setFont(font, size)
            t2 = t if k == 0 else t.replace("Internal Revenue Service",
                                             "Ace Financial %d-%d" % (page_no, k))
            if align == "center":
                c.drawCentredString(W / 2, _y(top), t2)
            else:
                c.drawString(L_MARGIN, _y(top), t2)
            top += 16
        top += 20


def page_colour_document(path, colour="#dbe4f0", pages=3, cover=None,
                         text_colour=(0, 0, 0), border=True, strip=None):
    """R1: `colour` over the whole sheet of every page (None: no page colour);
    `cover`: page 1's own full-sheet colour instead; `strip`: a running
    header strip's colour, 50pt at the top of every page, with header text."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    for n in range(1, pages + 1):
        if n == 1 and cover:
            _sheet(c, cover)
        elif colour:
            _sheet(c, colour)
        if strip:
            c.setFillColorRGB(*_rgb(strip))
            c.rect(0, H - 50, W, 50, fill=1, stroke=0)
            c.setFillColorRGB(1, 1, 1)
            c.setFont("Helvetica-Bold", 11)
            c.drawString(L_MARGIN, H - 30, "Federal Resume -- Jane A. Jones")
        if border:
            _page_border(c)
        _resume_page(c, n, text_colour=text_colour)
        c.showPage()
    c.save()
    return path


# --------------------------------------------------------------------- R2
R2_ENTRIES = [("SpinMedia, New York, NY", "May 2014 - August 2014"),
              ("Mad Science, Pittsburgh, PA", "September 2013 - April 2014"),
              ("Carnegie Mellon University, Pittsburgh, PA", "May 2013 - August 2013")]
R2_LIST = [("Advanced Data Analysis", "Microsoft Office"),
           ("Attitudes and Persuasion", "Adobe Creative Suite"),
           ("Psychology of Gender", "Spanish (Basic)"),
           ("Research Methods in Psychology", "SPSS")]


def two_sided_list_resume(path):
    """R2: entries with dates at a right tab, then a coursework list at the
    margin beside a skills list set flush right -- four right-aligned lines in
    a row, each beside a short left line."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    c.setFont("Times-Bold", 18)
    c.drawRightString(R_EDGE, _y(60), "Si K. Ology")
    c.setFont("Times-Bold", 11)
    c.drawString(L_MARGIN, _y(100), "RELEVANT EXPERIENCE")
    top = 118.0
    for entry, dates in R2_ENTRIES:
        c.setFont("Times-Bold", 10)
        c.drawString(L_MARGIN, _y(top), entry)
        c.drawRightString(R_EDGE, _y(top), dates)
        c.setFont("Times-Roman", 10)
        c.drawString(L_MARGIN + 18, _y(top + 13),
                     "•  Coordinated with internal teams to produce insights for the business.")
        c.drawString(L_MARGIN + 18, _y(top + 26),
                     "•  Assisted in creating monthly reports on the size of the audience.")
        top += 46
    c.setFont("Times-Bold", 10)
    c.drawString(L_MARGIN, _y(top + 10), "RELEVANT COURSEWORK")
    c.drawRightString(R_EDGE, _y(top + 10), "SKILLS")
    top += 26
    c.setFont("Times-Roman", 10)
    for left, right in R2_LIST:
        c.drawString(L_MARGIN, _y(top), left)
        c.drawRightString(R_EDGE, _y(top), right)
        top += 13
    c.save()
    return path


# --------------------------------------------------------------------- R3a
R3_ROWS = [("Carnegie Mellon University", "Pittsburgh, PA"),
           ("B.S. Information Systems", "Summer 2017"),
           ("Shanghai International Studies University", "Shanghai, China"),
           ("Study Abroad; Intermediate Chinese", "Summer 2014"),
           ("Carnegie Mellon University Division of Student Affairs", "Summer 2015")]


def left_tab_resume(path, tab_x=430.0):
    """R3a: each entry's place or date starts at ONE x (a left tab) and ends
    wherever its text ends, beside a label at the margin; headings carry a
    typed underscore rule to the right edge."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    c.setFont("Times-Bold", 14)
    c.drawCentredString(W / 2, _y(50), "Ruby (Hyun Hee) Rail")
    top = 84.0
    for heading in ("EDUCATION", "EXPERIENCE"):
        c.setFont("Times-Bold", 11)
        c.drawString(L_MARGIN, _y(top), heading)
        c.drawString(460.0, _y(top), "_" * 13)
        top += 16
        for label, field in R3_ROWS:
            c.setFont("Times-Bold" if "University" in label else "Times-Roman", 10)
            c.drawString(L_MARGIN, _y(top), label)
            c.setFont("Times-Italic", 10)
            c.drawString(tab_x, _y(top), field)
            top += 14
            # rows are a few among the page's lines, as in a real resume
            c.setFont("Times-Roman", 10)
            for b in ("Created custom software applications using Adobe Cold Fusion and SQL.",
                      "Improved customer service, streamlining business processes for dining."):
                c.drawString(L_MARGIN + 18, _y(top), "•  " + b)
                top += 13
        top += 14
    c.save()
    return path


def left_number_contents(path):
    """R3a control: a contents page whose page numbers are set at a LEFT tab
    (they start at one x, ragged by digit count), titles at the margin."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    c.setFont("Helvetica-Bold", 14)
    c.drawString(L_MARGIN, _y(70), "Contents")
    c.setFont("Helvetica", 10.5)
    top = 100.0
    for i, t in enumerate(("Introduction", "Scope of the review", "Method",
                           "Findings", "Recommendations", "Appendix A: Data",
                           "Appendix B: Glossary", "Index")):
        c.drawString(L_MARGIN, _y(top), t)
        c.drawString(470.0, _y(top), str(1 + 7 * i))
        top += 18
    c.save()
    return path


WORDS = ("the panel reviewed each application against the published criteria "
         "and recorded the reasons for its decision in the minutes of the "
         "meeting so that every applicant could see how it was reached").split()


def two_column_short_lines(path):
    """R3a control: two columns of ragged-right prose whose paragraphs end in
    short lines, the right column's lines all starting at its one left edge."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    c.setFont("Times-Roman", 10.5)
    for x0, x1 in ((L_MARGIN, 297.0), (315.0, R_EDGE)):
        top, k = 80.0, 0
        for para in range(6):
            for ln in range(5):
                line = []
                while True:
                    w = WORDS[k % len(WORDS)]
                    if stringWidth(" ".join(line + [w]), "Times-Roman", 10.5) > \
                            (x1 - x0) * (0.35 if ln == 4 else 1.0):
                        break
                    line.append(w)
                    k += 1
                c.drawString(x0, _y(top), " ".join(line))
                top += 13
            top += 8
    c.save()
    return path


def full_page_table(path, inset=36.0):
    """R1 control: a table drawn out to near the paper's edge -- its frame
    within the band a page border sits in -- whose row and column rules end
    on that frame. It is a table, not a page border."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    x0, y0, x1, y1 = inset, inset, W - inset, H - inset
    c.setLineWidth(1.0)
    c.rect(x0, y0, x1 - x0, y1 - y0, fill=0, stroke=1)
    cols = (x0, 200.0, 380.0, x1)
    for x in cols[1:-1]:
        c.line(x, y0, x, y1)
    rows = [y1 - 40 * k for k in range(1, 19)]
    for y in rows:
        c.line(x0, y, x1, y)
    c.setFont("Helvetica", 9)
    for r, y in enumerate([y1] + rows[:-1]):
        for k, (a, b) in enumerate(zip(cols, cols[1:])):
            c.drawString(a + 4, y - 22, "Row %d, column %d" % (r + 1, k + 1))
    c.save()
    return path
