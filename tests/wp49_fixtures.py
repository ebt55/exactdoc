"""Synthetic PDFs for WP49: tab- and right-aligned layouts read as tables.

Each builder draws the smallest page that shows ONE layout mechanism, the way
a word processor lays it out, and a control page that looks similar but is
the structure the converter must keep. They are generated at test time with
reportlab (no fixture bytes are committed) and parsed by the real PDFium
backend, so a test exercises the same path a conversion does.

A  right-tab fields          a resume's "City, ST" / dates set at a right tab
                             on the baselines of the left-hand entry lines,
                             between full-width bullets. Controls: a genuine
                             two-column page of justified prose, two columns
                             of short entries on one baseline grid (flush
                             left), a right-aligned pull quote beside prose.
B  heading underlines        section headings with a full-width rule under
                             each, over tab-aligned lists. Control: a
                             three-rule (booktabs) table.
C  multi-rectangle paths     a zebra table whose cell fills are drawn two
                             rectangles to a path object. Controls: vertical
                             and horizontal bar charts each drawn as one path
                             of rectangles.
D  per-level contents lines  a two-level table of contents whose levels'
                             page numbers end a few points apart (each level
                             exact). Control: a contents page with a FIXED run
                             of dots after each title, numbers wherever the
                             dots ended.
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


# --------------------------------------------------------------------- A
RESUME_ROWS = [
    ("Riverside High School, Public Schools of Town", "Town, MA",
     "Special Education Teacher", "August 2019 - Present"),
    ("Northfield Middle School", "Springfield, IL",
     "Long-Term Substitute Teacher", "January 2017 - June 2019"),
    ("ARISE Consulting Services, Inc.", "Cambridge, MA",
     "Behaviour Therapist, part-time", "May 2015 - December 2016"),
    ("Lakeside Academy", "Portland, OR",
     "Teaching Assistant", "September 2013 - May 2015"),
]
RESUME_BULLETS = [
    "Taught general and special education classes for students in grades six "
    "through eight in a co-taught setting",
    "Developed and implemented individual education plans with families and "
    "the school's support staff",
]


def right_tab_resume(path):
    """A: each entry is a bold employer line and an italic role line at the
    left margin, with the place and the dates set at a right tab on the SAME
    two baselines, then full-width bullets. The right-hand fields end at one
    x and start wherever their text makes them start."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    c.setFont("Times-Bold", 16)
    c.drawCentredString(W / 2, _y(60), "Jordan Sample")
    c.setFont("Times-Roman", 10)
    c.drawCentredString(W / 2, _y(76), "Boston, MA | jordan@example.com | (555) 555-0100")
    c.setFont("Times-Bold", 11)
    c.drawCentredString(W / 2, _y(104), "EXPERIENCE")
    top = 124.0
    for employer, place, role, dates in RESUME_ROWS:
        c.setFont("Times-Bold", 10.5)
        c.drawString(L_MARGIN, _y(top), employer)
        c.drawRightString(R_EDGE, _y(top), place)
        c.setFont("Times-Italic", 10.5)
        c.drawString(L_MARGIN, _y(top + 13), role)
        c.drawRightString(R_EDGE, _y(top + 13), dates)
        c.setFont("Times-Roman", 10.5)
        y = top + 28
        for b in RESUME_BULLETS:
            c.drawString(L_MARGIN + 6, _y(y), "•")
            c.drawString(L_MARGIN + 18, _y(y), b)
            y += 13
        top = y + 12
    c.setFont("Times-Bold", 11)
    c.drawCentredString(W / 2, _y(top + 6), "EDUCATION")
    top += 26
    for school, place, degree, date in (
            ("Lesley University", "Cambridge, MA",
             "Master of Education in Secondary Education", "June 2013"),
            ("State University", "Fitchburg, MA",
             "Bachelor of Arts, History", "May 2011")):
        c.setFont("Times-Bold", 10.5)
        c.drawString(L_MARGIN, _y(top), school)
        c.drawRightString(R_EDGE, _y(top), place)
        c.setFont("Times-Roman", 10.5)
        c.drawString(L_MARGIN, _y(top + 13), degree)
        c.drawRightString(R_EDGE, _y(top + 13), date)
        top += 36
    c.save()
    return path


TWO_COL_WORDS = ("the committee reviewed every submission against the published "
                 "criteria and recorded its reasons for each decision in the "
                 "minutes so that applicants could see how the panel had reached "
                 "its view on the merits of the case").split()


def _justified(c, x0, x1, top, n_lines, font="Times-Roman", size=10.5, lead=13.0):
    words, k = TWO_COL_WORDS * 20, 0
    for i in range(n_lines):
        line = []
        while k < len(words):
            trial = line + [words[k]]
            if stringWidth(" ".join(trial), font, size) > x1 - x0:
                break
            line, k = trial, k + 1
        gaps = max(1, len(line) - 1)
        spare = (x1 - x0) - sum(stringWidth(w, font, size) for w in line)
        x = x0
        c.setFont(font, size)
        for w in line:
            c.drawString(x, _y(top + i * lead), w)
            x += stringWidth(w, font, size) + spare / gaps
    return top + n_lines * lead


def two_column_prose(path):
    """A control: a real two-column page. Both columns are justified, so the
    right column's lines share a LEFT edge as well as a right one, and they
    run on line after line rather than standing beside one entry each."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    c.setFont("Times-Bold", 14)
    c.drawString(L_MARGIN, _y(70), "Annual review of the grants programme")
    _justified(c, L_MARGIN, 297.0, 100.0, 40)
    _justified(c, 315.0, R_EDGE, 100.0, 40)
    c.save()
    return path


GLOSSARY = [("ATO", "Authorization to operate"), ("BIA", "Business impact analysis"),
            ("CMVP", "Cryptographic module validation"), ("DRP", "Disaster recovery plan"),
            ("FIPS", "Federal information processing"), ("ISCM", "Continuous monitoring"),
            ("MOU", "Memorandum of understanding"), ("PIV", "Personal identity verification"),
            ("RMF", "Risk management framework"), ("SCRM", "Supply chain risk"),
            ("SLA", "Service level agreement"), ("TTX", "Tabletop exercise")]


def grid_aligned_columns(path):
    """A control: two columns of short entries set on one baseline grid, as a
    LaTeX or IRS two-column page sets them -- each right-column line beside a
    left-column line, short, but every one starting at the column's LEFT edge.
    The fields test must leave it to the column reader."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    c.setFont("Times-Bold", 13)
    c.drawString(L_MARGIN, _y(70), "Appendix B. Acronyms")
    top = 100.0
    c.setFont("Times-Roman", 10.5)
    for i, (ab, full) in enumerate(GLOSSARY * 2):
        x = L_MARGIN if i < len(GLOSSARY) else 315.0
        y = top + 26 * (i % len(GLOSSARY))
        c.setFont("Times-Bold", 10.5)
        c.drawString(x, _y(y), ab)
        c.setFont("Times-Roman", 10.5)
        c.drawString(x, _y(y + 13), full)
    c.save()
    return path


def right_aligned_sidebar(path):
    """A control: body prose at the left with a pull quote set flush RIGHT
    beside it, its lines on the body's baseline grid. Ragged-left, short and
    beside a left-hand line, like fields -- but it runs on line after line."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    c.setFont("Times-Bold", 14)
    c.drawString(L_MARGIN, _y(70), "Why the programme matters")
    words, k = TWO_COL_WORDS * 20, 0
    quote = ["“We saw every", "applicant treated", "the same way,", "whatever the size",
             "of the business,", "and that is what", "a public scheme", "has to promise.”",
             "— panel chair"]
    c.setFont("Times-Roman", 10.5)
    for i in range(30):
        line = []
        while k < len(words):
            trial = line + [words[k]]
            if stringWidth(" ".join(trial), "Times-Roman", 10.5) > 330:
                break
            line, k = trial, k + 1
        c.drawString(L_MARGIN, _y(100 + 13 * i), " ".join(line))
    c.setFont("Times-Italic", 10.5)
    for i, q in enumerate(quote):
        c.drawRightString(R_EDGE, _y(152 + 13 * i), q)
    c.save()
    return path


# --------------------------------------------------------------------- B
def underlined_sections(path):
    """B: section headings, each with a full-width rule under it, over
    entries with right-tab dates and a three-column tab-aligned skills list."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(W / 2, _y(60), "Jordan Sample")
    top = 96.0
    for heading, body in (("Education", "edu"), ("Technical Skills", "skills"),
                          ("Professional Experience", "exp")):
        c.setFont("Helvetica-Bold", 11)
        c.drawCentredString(W / 2, _y(top), heading)
        c.setLineWidth(0.75)
        c.line(L_MARGIN, _y(top + 4), R_EDGE, _y(top + 4))
        top += 20
        c.setFont("Helvetica", 9.5)
        if body == "edu":
            for school, date in (("Harbor University Extension School", "May 2021"),
                                 ("University of the North", "June 2016")):
                c.setFont("Helvetica-Bold", 9.5)
                c.drawString(L_MARGIN, _y(top), school)
                c.setFont("Helvetica", 9.5)
                c.drawRightString(R_EDGE, _y(top), date)
                c.drawString(L_MARGIN, _y(top + 12), "Master of Liberal Arts, Information Management Systems")
                c.drawString(L_MARGIN + 8, _y(top + 24), "•")
                c.drawString(L_MARGIN + 18, _y(top + 24), "Capstone Project: Enterprise Data Lake")
                top += 40
        elif body == "skills":
            cols = (L_MARGIN + 8, 230.0, 380.0)
            rows = (("Machine Learning", "Python/Scikit-learn", "Data Visualization"),
                    ("Quantitative Analysis", "Cloud Computing", "Java/C#"),
                    ("Unix Scripting", "Oracle/SQL Server", "Data Warehouse/ETL"),
                    ("RDBMS Tuning", "Network Protocols", "Web Development"))
            for row in rows:
                for x, t in zip(cols, row):
                    c.drawString(x, _y(top), "•")
                    c.drawString(x + 9, _y(top), t)
                top += 12
            top += 10
        else:
            c.setFont("Helvetica-Bold", 9.5)
            c.drawString(L_MARGIN, _y(top), "Rande Corporate & Investment Banking")
            c.setFont("Helvetica", 9.5)
            c.drawRightString(R_EDGE, _y(top), "Detroit, MI")
            c.drawString(L_MARGIN + 8, _y(top + 12), "•")
            c.drawString(L_MARGIN + 18, _y(top + 12),
                         "Led a team of six people to manage and support a trading platform")
            top += 30
    c.save()
    return path


def booktabs_table(path):
    """B control: a three-rule table -- top rule, rule under the header row,
    bottom rule -- whose rows fill every column."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    c.setFont("Helvetica", 10)
    c.drawString(L_MARGIN, _y(80), "Table 2. Results by region.")
    xs = (L_MARGIN, 220.0, 320.0, 420.0)
    c.setLineWidth(0.8)
    c.line(L_MARGIN, _y(92), R_EDGE, _y(92))
    for x, t in zip(xs, ("Region", "2022", "2023", "Change")):
        c.drawString(x, _y(106), t)
    c.setLineWidth(0.5)
    c.line(L_MARGIN, _y(111), R_EDGE, _y(111))
    top = 126.0
    for row in (("North", "1,204", "1,322", "+9.8%"), ("South", "988", "1,010", "+2.2%"),
                ("East", "1,571", "1,498", "-4.6%"), ("West", "640", "702", "+9.7%")):
        for x, t in zip(xs, row):
            c.drawString(x, _y(top), t)
        top += 14
    c.setLineWidth(0.8)
    c.line(L_MARGIN, _y(top - 6), R_EDGE, _y(top - 6))
    c.drawString(L_MARGIN, _y(top + 20), "Source: regional returns.")
    c.save()
    return path


# --------------------------------------------------------------------- C
def _two_rect_path(c, r1, r2, fill):
    """Two cell fills in ONE path object, as some producers batch them."""
    c.setFillColorRGB(*fill)
    p = c.beginPath()
    p.rect(*r1)
    p.rect(*r2)
    c.drawPath(p, fill=1, stroke=0)


def zebra_multirect_table(path):
    """C: a financial table whose cell backgrounds alternate white and light
    grey, each row's '$' cell and amount cell drawn as two rectangles in one
    path, figures right-aligned, a rule under the last amount."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    c.setFont("Times-Roman", 10)
    c.drawString(L_MARGIN, _y(70), "A summary of net investment income follows (dollars in millions).")
    labels = ("Dividend income", "Interest and other investment income",
              "Pre-tax net investment income", "Income taxes",
              "Net investment income", "Effective income tax rate")
    vals = (("5,500", "6,039", "5,060"), ("6,081", "1,685", "589"),
            ("11,581", "7,724", "5,649"), ("2,014", "1,240", "842"),
            ("9,567", "6,484", "4,807"), ("17.4%", "16.0%", "14.9%"))
    cols = ((330.0, 380.0), (395.0, 445.0), (460.0, 510.0))
    c.setFont("Times-Bold", 9)
    for (a, b), yr in zip(cols, ("2023", "2022", "2021")):
        c.drawRightString(b, _y(92), yr)
    top = 96.0
    for i, (lab, row) in enumerate(zip(labels, vals)):
        grey = (0.93, 0.93, 0.93) if i % 2 else (1, 1, 1)
        y0 = H - (top + 12)
        # the label cell and the row's last (end-padding) cell share one path,
        # far apart, so the path's box spans the whole row; every other cell
        # is a rectangle of its own
        _two_rect_path(c, (L_MARGIN, y0, 250, 12), (cols[-1][1] + 2, y0, 8, 12), grey)
        c.setFillColorRGB(*grey)
        for a, b in cols:
            c.rect(a - 8, y0, 8, 12, fill=1, stroke=0)
            c.rect(a, y0, b - a, 12, fill=1, stroke=0)
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Times-Roman", 9)
        c.drawString(L_MARGIN + 2, _y(top + 9), lab)
        for (a, b), v in zip(cols, row):
            if i == 0:
                c.drawString(a - 7, _y(top + 9), "$")
            c.drawRightString(b, _y(top + 9), v)
        top += 12
    c.setLineWidth(0.5)
    for a, b in cols:
        c.line(a, _y(top - 12), b, _y(top - 12))
    c.setFont("Times-Roman", 10)
    c.drawString(L_MARGIN, _y(top + 24), "Dividend income declined in 2023 compared to 2022.")
    c.save()
    return path


def one_path_bar_chart(path):
    """C control: a bar chart drawn as ONE path of rectangles of different
    heights on a shared baseline, with its axis labels."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    c.setFont("Helvetica", 10)
    c.drawString(L_MARGIN, _y(70), "Figure 1. Applications received per year.")
    c.setFillColorRGB(0.2, 0.4, 0.7)
    p = c.beginPath()
    base = H - 300
    for i, h in enumerate((60, 110, 85, 150, 130)):
        p.rect(L_MARGIN + 30 + i * 60, base, 36, h)
    c.drawPath(p, fill=1, stroke=0)
    c.setFillColorRGB(0, 0, 0)
    for i, yr in enumerate(("2019", "2020", "2021", "2022", "2023")):
        c.drawString(L_MARGIN + 34 + i * 60, base - 14, yr)
    c.drawString(L_MARGIN, _y(330), "Applications rose in four of the five years.")
    c.save()
    return path


def one_path_horizontal_bars(path):
    """C control: a HORIZONTAL bar chart drawn as one path -- the bars share
    their LEFT edge, not a bottom, and differ in length, with a label beside
    each. Split naively into rectangles it looks like table stripes."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    c.setFont("Helvetica", 10)
    c.drawString(L_MARGIN, _y(70), "Figure 2. Share of respondents by region.")
    c.setFillColorRGB(0.2, 0.4, 0.7)
    p = c.beginPath()
    x0 = 200.0
    for i, w in enumerate((220, 160, 300, 90, 190)):
        p.rect(x0, H - (100 + 22 * i + 14), w, 14)
    c.drawPath(p, fill=1, stroke=0)
    c.setFillColorRGB(0, 0, 0)
    for i, reg in enumerate(("North", "South", "East", "West", "Central")):
        c.drawRightString(x0 - 8, H - (100 + 22 * i + 10), reg)
    c.drawString(L_MARGIN, _y(240), "East led every year of the survey.")
    c.save()
    return path


# --------------------------------------------------------------------- D
TOC_ENTRIES = [
    (1, "Overview", "2"), (2, "Background and scope", "3"),
    (1, "Principles", "4"), (2, "Ownership of outcomes", "5"),
    (2, "Radical transparency", "6"), (1, "Tactics", "8"),
    (2, "Hardening guides", "10"), (2, "Recommendations for customers", "12"),
    (1, "Disclaimer", "13"), (1, "Resources", "13"),
]
# Word sets every level's number at ONE right tab, but the tab aligns the end
# of a run that carries a trailing space, and each level's style sets that
# space in its own face and size: the visible numbers of the two levels end a
# few points apart, every number of one level at exactly the same x.
TOC_EDGE = {1: 543.3, 2: 539.5}


def _leader_line(c, x0, edge, top, label, num, font, size):
    tail = " " + num
    room = edge - x0 - stringWidth(label + " " + tail, font, size)
    n = max(4, int(room / stringWidth(".", font, size)))
    c.setFont(font, size)
    c.drawRightString(edge, _y(top), label + " " + "." * n + tail)


def two_level_contents(path):
    """D: a contents page in two levels, each level's numbers flush at its
    own edge, the two edges 3.8pt apart."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    c.setFont("Helvetica", 16)
    c.drawString(L_MARGIN, _y(80), "Table of Contents")
    top = 110.0
    for level, label, num in TOC_ENTRIES:
        x0 = L_MARGIN if level == 1 else L_MARGIN + 13
        font = "Helvetica-Bold" if level == 1 else "Helvetica"
        _leader_line(c, x0, TOC_EDGE[level], top, label, num, font, 10.5)
        top += 21.5
    c.save()
    return path


def fixed_dot_contents(path):
    """D control: each title followed by the same fixed run of dots and its
    number, so the numbers end wherever the title made them end."""
    c = _canvas.Canvas(path, pagesize=(W, H))
    c.setFont("Helvetica", 16)
    c.drawString(L_MARGIN, _y(80), "Contents")
    top = 110.0
    c.setFont("Helvetica", 10.5)
    for _level, label, num in TOC_ENTRIES:
        c.drawString(L_MARGIN, _y(top), label + " " + "." * 40 + " " + num)
        top += 21.5
    c.save()
    return path
