#!/usr/bin/env python3
"""Synthesize Claude-style PDFs (ReportLab) as a test corpus for exactdoc.

All text content is original/synthetic (fictitious companies and numbers).
Docs mimic the structural/design patterns Claude commonly emits:
cover color bands, colored headings, callout boxes, shaded tables, lists,
code blocks, vector charts, stat cards, two-column paper, footers w/ page numbers.
"""
import os
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer,
    Table, TableStyle, PageBreak, HRFlowable, Preformatted, ListFlowable,
    ListItem, NextPageTemplate, FrameBreak, Image,
)
from reportlab.graphics.shapes import Drawing, Rect, String, Line, PolyLine, Circle

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "pdfs")
os.makedirs(OUT, exist_ok=True)
W, H = LETTER

# ---------------------------------------------------------------- shared styles
def ps(name, **kw):
    base = dict(fontName="Helvetica", fontSize=10.5, leading=15, textColor=HexColor("#1f2937"))
    base.update(kw)
    return ParagraphStyle(name, **base)

NAVY = HexColor("#1e3a5f"); BLUE = HexColor("#2563eb"); LBLUE = HexColor("#eff6ff")
GREY = HexColor("#6b7280"); TEAL = HexColor("#0f766e"); AMBER = HexColor("#f59e0b")
LAMBER = HexColor("#fef3c7"); INDIGO = HexColor("#4f46e5"); VIOLET = HexColor("#7c3aed")
CODEBG = HexColor("#f3f4f6"); INK = HexColor("#1f2937")

def bar_chart(width=430, height=190, color=BLUE, labels=None, values=None, title=""):
    labels = labels or ["2022", "2023", "2024", "2025", "2026"]
    values = values or [18, 27, 41, 63, 88]
    d = Drawing(width, height)
    x0, y0, cw, ch = 46, 30, width - 66, height - 52
    d.add(Line(x0, y0, x0 + cw, y0, strokeColor=HexColor("#9ca3af"), strokeWidth=0.8))
    d.add(Line(x0, y0, x0, y0 + ch, strokeColor=HexColor("#9ca3af"), strokeWidth=0.8))
    vmax = max(values) * 1.15
    for g in range(1, 5):
        gy = y0 + ch * g / 4.0
        d.add(Line(x0, gy, x0 + cw, gy, strokeColor=HexColor("#e5e7eb"), strokeWidth=0.5))
        d.add(String(x0 - 6, gy - 3, f"{int(vmax*g/4)}", fontName="Helvetica", fontSize=7,
                     fillColor=GREY, textAnchor="end"))
    bw = cw / len(values) * 0.55
    step = cw / len(values)
    for i, v in enumerate(values):
        bx = x0 + step * i + (step - bw) / 2
        bh = ch * v / vmax
        d.add(Rect(bx, y0, bw, bh, fillColor=color, strokeColor=None))
        d.add(String(bx + bw / 2, y0 - 12, labels[i], fontName="Helvetica", fontSize=8,
                     fillColor=INK, textAnchor="middle"))
        d.add(String(bx + bw / 2, y0 + bh + 4, str(v), fontName="Helvetica-Bold", fontSize=8,
                     fillColor=color, textAnchor="middle"))
    if title:
        d.add(String(x0, y0 + ch + 8, title, fontName="Helvetica-Bold", fontSize=9.5, fillColor=INK))
    return d

def line_chart(width=430, height=180, color=INDIGO):
    d = Drawing(width, height)
    x0, y0, cw, ch = 40, 26, width - 60, height - 46
    d.add(Line(x0, y0, x0 + cw, y0, strokeColor=HexColor("#9ca3af"), strokeWidth=0.8))
    d.add(Line(x0, y0, x0, y0 + ch, strokeColor=HexColor("#9ca3af"), strokeWidth=0.8))
    vals = [12, 19, 17, 28, 36, 33, 47, 58]
    labs = ["Q1", "Q2", "Q3", "Q4", "Q1", "Q2", "Q3", "Q4"]
    vmax = max(vals) * 1.2
    pts = []
    for i, v in enumerate(vals):
        px = x0 + cw * i / (len(vals) - 1)
        py = y0 + ch * v / vmax
        pts += [px, py]
        d.add(String(px, y0 - 12, labs[i], fontName="Helvetica", fontSize=7.5,
                     fillColor=GREY, textAnchor="middle"))
    d.add(PolyLine(pts, strokeColor=color, strokeWidth=2))
    for i in range(0, len(pts), 2):
        d.add(Circle(pts[i], pts[i + 1], 2.6, fillColor=color, strokeColor=None))
    d.add(String(x0, y0 + ch + 6, "Quarterly active deployments (thousands)",
                 fontName="Helvetica-Bold", fontSize=9, fillColor=INK))
    return d

def callout(text, fill=LBLUE, bar=BLUE, label="Key Insight", body_size=10):
    p = Paragraph(f'<b><font color="#1e3a5f">{label}:</font></b> {text}',
                  ps("co", fontSize=body_size, leading=body_size + 4))
    t = Table([[p]], colWidths=[W - 108 - 6])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), fill),
        ("LINEBEFORE", (0, 0), (0, -1), 3, bar),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    return t

def code_block(code, width=W - 108):
    pre = Preformatted(code, ParagraphStyle("code", fontName="Courier", fontSize=8.5,
                                            leading=11.5, textColor=HexColor("#111827")))
    t = Table([[pre]], colWidths=[width])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CODEBG),
        ("BOX", (0, 0), (-1, -1), 0.75, HexColor("#d1d5db")),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t

LOREM = ("Modern inference workloads exhibit sharply bimodal traffic patterns, with sustained "
         "baseline demand punctuated by bursts that exceed steady-state volume by an order of "
         "magnitude. Provisioning for peak wastes capacity; provisioning for baseline degrades "
         "latency guarantees precisely when demand is highest. ")
LOREM2 = ("Organizations that adopt a tiered execution fabric report materially better cost "
          "curves than those scaling monolithic clusters, because scheduling decisions can "
          "exploit heterogeneity in both hardware and request criticality. ")
LOREM3 = ("The remainder of this document quantifies these effects across three deployment "
          "archetypes and proposes an adoption sequence that minimizes migration risk while "
          "preserving existing service level objectives. ")

# ================================================================ DOC 1: whitepaper
def doc1():
    path = os.path.join(OUT, "01_whitepaper_market.pdf")
    title = "The Economics of Tiered AI Inference"
    subtitle = "A Meridian Analytics Whitepaper"

    def first_page(c, doc):
        c.saveState()
        c.setFillColor(NAVY); c.rect(0, H - 170, W, 170, fill=1, stroke=0)
        c.setFillColor(HexColor("#f59e0b")); c.rect(0, H - 174, W, 4, fill=1, stroke=0)
        c.setFillColor(white); c.setFont("Helvetica-Bold", 25)
        c.drawString(54, H - 92, title)
        c.setFont("Helvetica", 12.5); c.setFillColor(HexColor("#bfdbfe"))
        c.drawString(54, H - 116, subtitle)
        c.setFont("Helvetica", 9.5); c.setFillColor(HexColor("#93c5fd"))
        c.drawString(54, H - 148, "July 2026  |  Research Division  |  meridian-analytics.example.com")
        footer(c, doc)
        c.restoreState()

    def later_page(c, doc):
        c.saveState()
        c.setFillColor(NAVY); c.rect(0, H - 30, W, 30, fill=1, stroke=0)
        c.setFillColor(white); c.setFont("Helvetica-Bold", 8.5)
        c.drawString(54, H - 19, title.upper())
        c.setFillColor(HexColor("#bfdbfe")); c.setFont("Helvetica", 8.5)
        c.drawRightString(W - 54, H - 19, "MERIDIAN ANALYTICS")
        footer(c, doc)
        c.restoreState()

    def footer(c, doc):
        c.setStrokeColor(HexColor("#d1d5db")); c.setLineWidth(0.6)
        c.line(54, 46, W - 54, 46)
        c.setFont("Helvetica", 8); c.setFillColor(GREY)
        c.drawString(54, 34, "© 2026 Meridian Analytics — Confidential")
        c.drawRightString(W - 54, 34, f"Page {c.getPageNumber()}")

    doc = SimpleDocTemplate(path, pagesize=LETTER, leftMargin=54, rightMargin=54,
                            topMargin=54, bottomMargin=64, title=title, author="Meridian Analytics")
    h1 = ps("h1", fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=NAVY,
            spaceBefore=18, spaceAfter=8)
    h2 = ps("h2", fontName="Helvetica-Bold", fontSize=12.5, leading=16, textColor=BLUE,
            spaceBefore=13, spaceAfter=6)
    body = ps("body", alignment=TA_JUSTIFY, spaceAfter=8)
    story = [
        Spacer(1, 132),
        Paragraph("Executive Summary", h1),
        HRFlowable(width="100%", thickness=1, color=HexColor("#e5e7eb"), spaceAfter=10),
        Paragraph(LOREM + LOREM2 + "This paper introduces a cost model that treats inference "
                  "capacity as a portfolio rather than a pipeline.", body),
        Paragraph(LOREM3 + "Readers responsible for capacity planning should focus on Sections "
                  "2 and 4; readers responsible for procurement should focus on Section 3.", body),
        Spacer(1, 4),
        callout("Across the 41 organizations surveyed, tiered inference reduced cost per "
                "thousand requests by a median of 38% while improving p99 latency by 22%."),
        Paragraph("1. Market Context", h1),
        Paragraph(LOREM + "Vendors have responded with a proliferation of accelerator classes, "
                  "each optimized for a different point on the latency-throughput frontier.", body),
        Paragraph("1.1 Demand-side dynamics", h2),
        Paragraph(LOREM2 + "Buyers increasingly negotiate committed-use discounts against a "
                  "blended fleet rather than a single instance family.", body),
        ListFlowable([
            ListItem(Paragraph("Baseline traffic grows 3.1× year over year in our panel, while "
                               "peak-to-baseline ratios remain near 9:1.", body)),
            ListItem(Paragraph("Latency-sensitive requests represent 17% of volume but 44% of "
                               "infrastructure spend.", body)),
            ListItem(Paragraph("Batch-tolerant workloads are the fastest-growing segment, at "
                               "58% year over year.", body)),
        ], bulletType="bullet", start="•", leftIndent=18),
        Spacer(1, 6),
        Paragraph("1.2 Supply-side response", h2),
        Paragraph("Accelerator roadmaps now bifurcate into throughput-optimized and "
                  "latency-optimized lines. The table below summarizes list pricing normalized "
                  "to a common benchmark unit.", body),
        Spacer(1, 4),
    ]
    tbl = Table([
        ["Tier", "Hardware class", "Cost / 1K req", "p99 latency", "Best fit"],
        ["Realtime", "Latency-optimized", "$4.20", "180 ms", "Interactive agents"],
        ["Standard", "Balanced", "$1.85", "650 ms", "API workloads"],
        ["Batch", "Throughput-optimized", "$0.62", "8 s", "Offline enrichment"],
        ["Spot", "Preemptible mix", "$0.31", "best effort", "Experimentation"],
    ], colWidths=[70, 130, 85, 80, 139])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("TEXTCOLOR", (0, 1), (-1, -1), INK),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, HexColor("#f8fafc")]),
        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#cbd5e1")),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [
        tbl,
        Paragraph('<font size="8.5" color="#6b7280">Table 1: Normalized pricing across '
                  'inference tiers, June 2026 list prices.</font>', ps("cap", spaceBefore=4, spaceAfter=10)),
        Paragraph("2. Cost Model", h1),
        Paragraph("We model total cost as the sum of tier-level commitments plus overflow "
                  "penalties. Fleet growth under the tiered strategy is shown below.", body),
        Spacer(1, 6),
        bar_chart(title="Figure 1: Modeled fleet spend under tiered strategy ($M)"),
        Spacer(1, 10),
        Paragraph("2.1 Sensitivity", h2),
        Paragraph(LOREM2 + "Sensitivity analysis indicates the crossover point sits near 41% "
                  "batch-tolerant share for typical enterprise mixes.", body),
        ListFlowable([
            ListItem(Paragraph("Estimate the batch-tolerant share of current traffic.", body)),
            ListItem(Paragraph("Negotiate committed use only for the realtime tier.", body)),
            ListItem(Paragraph("Route overflow to spot capacity with graceful degradation.", body)),
            ListItem(Paragraph("Re-evaluate the mix quarterly against observed telemetry.", body)),
        ], bulletType="1", leftIndent=18),
        Spacer(1, 6),
        callout("Committed-use discounts applied to the wrong tier are the single largest "
                "source of waste we observed — median overspend of $2.4M annually.",
                fill=LAMBER, bar=AMBER, label="Risk"),
        Paragraph("3. Procurement Playbook", h1),
        Paragraph(LOREM3 + 'A worked example with editable assumptions is available at '
                  '<link href="https://meridian-analytics.example.com/models" color="#2563eb">'
                  '<u>meridian-analytics.example.com/models</u></link>.', body),
        Paragraph(LOREM + LOREM2, body),
        Paragraph("4. Conclusion", h1),
        Paragraph("Treating inference as a portfolio converts an infrastructure argument into "
                  "a financial one. " + LOREM3, body),
    ]
    doc.build(story, onFirstPage=first_page, onLaterPages=later_page)

# ================================================================ DOC 2: two-column paper
def doc2():
    path = os.path.join(OUT, "02_research_paper.pdf")
    doc = BaseDocTemplate(path, pagesize=LETTER, leftMargin=58, rightMargin=58,
                          topMargin=58, bottomMargin=58, title="Adaptive Speculative Decoding")
    colw = (W - 116 - 24) / 2.0
    title_frame = Frame(58, H - 58 - 150, W - 116, 150, id="title")
    colL_first = Frame(58, 58, colw, H - 116 - 158, id="c1f")
    colR_first = Frame(58 + colw + 24, 58, colw, H - 116 - 158, id="c2f")
    colL = Frame(58, 58, colw, H - 116, id="c1")
    colR = Frame(58 + colw + 24, 58, colw, H - 116, id="c2")

    def pnum(c, doc):
        c.saveState(); c.setFont("Times-Roman", 9); c.setFillColor(INK)
        c.drawCentredString(W / 2, 36, str(c.getPageNumber())); c.restoreState()

    doc.addPageTemplates([
        PageTemplate(id="First", frames=[title_frame, colL_first, colR_first], onPage=pnum),
        PageTemplate(id="Later", frames=[colL, colR], onPage=pnum),
    ])
    t_title = ps("t", fontName="Times-Bold", fontSize=17, leading=21, alignment=TA_CENTER,
                 textColor=HexColor("#111111"))
    t_auth = ps("a", fontName="Times-Roman", fontSize=11, leading=14, alignment=TA_CENTER, spaceBefore=10)
    t_aff = ps("af", fontName="Times-Italic", fontSize=9.5, leading=12, alignment=TA_CENTER,
               textColor=HexColor("#444444"), spaceBefore=2)
    sec = ps("sec", fontName="Times-Bold", fontSize=11.5, leading=14, spaceBefore=10, spaceAfter=4,
             textColor=HexColor("#111111"))
    pbody = ps("pb", fontName="Times-Roman", fontSize=9.5, leading=12.2, alignment=TA_JUSTIFY,
               spaceAfter=5, textColor=HexColor("#111111"))
    abst = ps("ab", fontName="Times-Roman", fontSize=9, leading=11.5, alignment=TA_JUSTIFY,
              textColor=HexColor("#111111"))
    story = [
        Paragraph("Adaptive Speculative Decoding under Heterogeneous Draft Models", t_title),
        Paragraph("Priya Raman&nbsp;&nbsp;&nbsp;Diego Álvarez&nbsp;&nbsp;&nbsp;Hannah Cole", t_auth),
        Paragraph("Institute for Efficient Computation, Basel", t_aff),
        NextPageTemplate("Later"),
        FrameBreak(),
        Paragraph("<b>Abstract</b>", sec),
        Paragraph("Speculative decoding accelerates autoregressive generation by drafting "
                  "tokens with a small model and verifying them with a large one. Fixed draft "
                  "models, however, leave acceptance rates on the table when input difficulty "
                  "varies. We introduce ASD, a router that selects among heterogeneous draft "
                  "models per segment using a lightweight difficulty estimator. On a mixed "
                  "workload, ASD improves throughput by 1.9× over the best fixed draft while "
                  "matching output distributions exactly.", abst),
        Paragraph("1&nbsp;&nbsp;Introduction", sec),
        Paragraph("Large-model inference remains dominated by sequential token generation. "
                  "Speculative methods amortize this cost, but their benefit hinges on the "
                  "acceptance rate of drafted tokens, which varies sharply with content "
                  "difficulty. Prior work fixes a single draft model ahead of time, implicitly "
                  "assuming difficulty is stationary. It is not.", pbody),
        Paragraph("We observe that acceptance traces exhibit regime shifts at segment "
                  "boundaries — code blocks, tables, and quoted material each favor different "
                  "drafters. This motivates a per-segment routing decision.", pbody),
        Paragraph("2&nbsp;&nbsp;Method", sec),
        Paragraph("ASD maintains a pool of draft models spanning three size classes. A "
                  "difficulty estimator computes features from the last 64 accepted tokens: "
                  "entropy of the verifier distribution, token rarity, and structural cues. A "
                  "bandit policy maps the feature vector to a drafter, updating its estimates "
                  "from observed acceptance.", pbody),
        Paragraph("Crucially, verification is unchanged, so the sampled distribution is "
                  "identical to standard decoding. The router adds 0.3% overhead.", pbody),
        Spacer(1, 4),
        bar_chart(width=colw - 6, height=150, color=TEAL,
                  labels=["S", "M", "L", "ASD"], values=[100, 138, 121, 190],
                  title="Fig. 1: Relative throughput (%)"),
        Spacer(1, 6),
        Paragraph("3&nbsp;&nbsp;Results", sec),
        Paragraph("Table 1 reports throughput and acceptance across workloads. ASD dominates "
                  "fixed drafters on mixed content and is never worse than the best fixed "
                  "choice by more than 2%.", pbody),
        Spacer(1, 3),
    ]
    rt = Table([
        ["Workload", "Best fixed", "ASD", "Δ"],
        ["Prose", "1.42×", "1.51×", "+6%"],
        ["Code", "1.66×", "1.83×", "+10%"],
        ["Mixed", "1.31×", "1.90×", "+45%"],
    ], colWidths=[(colw - 6) * f for f in (0.34, 0.26, 0.2, 0.2)])
    rt.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"), ("FONTNAME", (0, 1), (-1, -1), "Times-Roman"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("LINEABOVE", (0, 0), (-1, 0), 0.9, HexColor("#111111")),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, HexColor("#111111")),
        ("LINEBELOW", (0, -1), (-1, -1), 0.9, HexColor("#111111")),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story += [
        rt,
        Paragraph('<font size="8">Table 1: Throughput vs. the best fixed draft model.</font>',
                  ps("c2cap", fontName="Times-Italic", fontSize=8, leading=10, spaceBefore=3,
                     spaceAfter=8, alignment=TA_CENTER)),
        Paragraph("4&nbsp;&nbsp;Related Work", sec),
        Paragraph("Speculative decoding builds on rejection-sampling equivalence results; "
                  "subsequent variants explore tree drafting, self-drafting, and early exit. "
                  "Router-based model selection appears in serving literature but has not been "
                  "applied per-segment within a single generation.", pbody),
        Paragraph("5&nbsp;&nbsp;Conclusion", sec),
        Paragraph("Difficulty-aware routing recovers headroom that fixed draft models leave "
                  "behind, with no distributional cost. Future work extends the estimator to "
                  "multimodal inputs.", pbody),
        Paragraph("References", sec),
    ]
    ref = ps("ref", fontName="Times-Roman", fontSize=8.5, leading=10.5, leftIndent=12,
             firstLineIndent=-12, spaceAfter=3, textColor=HexColor("#111111"))
    story += [
        Paragraph("[1] Raman, P. et al. Segment-aware inference schedulers. In Proc. ESC, 2025.", ref),
        Paragraph("[2] Álvarez, D. and Cole, H. Bandit routing for serving fleets. J. Systems ML, 2024.", ref),
        Paragraph("[3] Cole, H. Difficulty estimation from verifier entropy. Workshop on Eff. NLP, 2025.", ref),
    ]
    doc.build(story)

# ================================================================ DOC 3: technical report
def doc3():
    path = os.path.join(OUT, "03_tech_report_code.pdf")
    title = "Sentinel SDK — Integration Guide"

    def on_page(c, doc):
        c.saveState()
        c.setStrokeColor(TEAL); c.setLineWidth(2)
        c.line(54, H - 40, W - 54, H - 40)
        c.setFont("Helvetica-Bold", 9); c.setFillColor(TEAL)
        c.drawString(54, H - 34, "SENTINEL SDK")
        c.setFont("Helvetica", 9); c.setFillColor(GREY)
        c.drawRightString(W - 54, H - 34, "v3.2 — July 2026")
        c.setFont("Helvetica", 8); c.setFillColor(GREY)
        c.drawCentredString(W / 2, 32, f"— {c.getPageNumber()} —")
        c.restoreState()

    doc = SimpleDocTemplate(path, pagesize=LETTER, leftMargin=54, rightMargin=54,
                            topMargin=72, bottomMargin=60, title=title)
    h1 = ps("h1", fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=TEAL,
            spaceBefore=16, spaceAfter=7)
    h2 = ps("h2", fontName="Helvetica-Bold", fontSize=11.5, leading=15, textColor=HexColor("#115e59"),
            spaceBefore=11, spaceAfter=5)
    body = ps("body", spaceAfter=7)
    mono_inline = 'fontName="Courier"'
    story = [
        Paragraph(title, ps("t", fontName="Helvetica-Bold", fontSize=21, leading=26,
                            textColor=HexColor("#134e4a"), spaceAfter=4)),
        Paragraph("Instrument request pipelines with anomaly detection in under ten minutes.",
                  ps("sub", fontSize=11, textColor=GREY, spaceAfter=14)),
        HRFlowable(width="100%", thickness=1.2, color=TEAL, spaceAfter=12),
        Paragraph("1. Installation", h1),
        Paragraph("Sentinel ships as a single package with zero runtime dependencies. Install "
                  "from the package index and verify the CLI is on your path:", body),
        code_block("pip install sentinel-sdk\nsentinel --version\n# sentinel 3.2.1 (python 3.11)"),
        Spacer(1, 8),
        Paragraph("2. Quickstart", h1),
        Paragraph("The minimal integration wraps your handler with a detector. Thresholds "
                  "adapt automatically after the warmup window:", body),
        code_block(
            "from sentinel import Detector, Policy\n\n"
            "detector = Detector(\n"
            "    policy=Policy.adaptive(warmup=500),\n"
            "    channels=[\"latency\", \"error_rate\", \"payload_entropy\"],\n"
            ")\n\n"
            "@detector.guard\n"
            "def handle(request):\n"
            "    return downstream.process(request)"),
        Spacer(1, 8),
        callout("The guard decorator adds ~40µs of overhead per call. For hot paths above "
                "50K RPS, use the batched API described in Section 4.",
                fill=LAMBER, bar=AMBER, label="Performance note", body_size=9.5),
        Paragraph("3. Configuration Reference", h1),
        Paragraph("All options can be set via constructor, environment, or config file. "
                  "Environment variables take precedence.", body),
    ]
    cfg = Table([
        ["Parameter", "Type", "Default", "Description"],
        ["policy", "Policy", "adaptive(500)", "Detection policy and warmup window"],
        ["channels", "list[str]", "[\"latency\"]", "Signals monitored per request"],
        ["sink", "Sink", "stdout", "Where verdicts are emitted"],
        ["sample_rate", "float", "1.0", "Fraction of traffic inspected"],
        ["fail_open", "bool", "True", "Pass traffic if detector errors"],
    ], colWidths=[92, 70, 100, 242])
    cfg.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#0f766e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (0, -1), "Courier"),
        ("FONTNAME", (1, 1), (2, -1), "Courier"),
        ("FONTNAME", (3, 1), (3, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 1), (-1, -1), INK),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, HexColor("#f0fdfa")]),
        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#99f6e4")),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
    ]))
    story += [
        cfg,
        Paragraph('<font size="8.5" color="#6b7280">Table 2: Constructor parameters.</font>',
                  ps("cap3", spaceBefore=4, spaceAfter=10)),
        Paragraph("4. Batched Verdicts", h1),
        Paragraph("For high-throughput services, evaluate verdicts asynchronously in batches. "
                  "The detector coalesces up to <font face=\"Courier\">max_batch</font> "
                  "requests per tick:", body),
        code_block(
            "async def pump(queue, detector):\n"
            "    while True:\n"
            "        batch = await queue.take(max_batch=256, timeout_ms=5)\n"
            "        verdicts = detector.evaluate(batch)\n"
            "        for v in verdicts.flagged():\n"
            "            await quarantine.put(v.request_id)"),
        Spacer(1, 8),
        callout("Never block the request path on sink I/O. Configure "
                "sink=Sink.buffered(...) in production deployments.",
                label="Warning", fill=HexColor("#fee2e2"), bar=HexColor("#dc2626"), body_size=9.5),
        Paragraph("5. Verdict Lifecycle", h2),
        ListFlowable([
            ListItem(Paragraph("Capture — signals sampled from the live request.", body)),
            ListItem(Paragraph("Score — policy computes an anomaly score per channel.", body)),
            ListItem(Paragraph("Decide — scores fold into a verdict with a confidence bound.", body)),
            ListItem(Paragraph("Emit — verdicts stream to the configured sink.", body)),
        ], bulletType="1", leftIndent=18),
    ]
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)

# ================================================================ DOC 4: executive brief
def doc4():
    path = os.path.join(OUT, "04_exec_brief.pdf")
    title = "State of Agent Operations 2026"

    def first(c, doc):
        c.saveState()
        c.setFillColor(HexColor("#312e81")); c.rect(0, H - 130, W, 130, fill=1, stroke=0)
        c.setFillColor(INDIGO); c.rect(0, H - 138, W, 8, fill=1, stroke=0)
        c.setFillColor(white); c.setFont("Helvetica-Bold", 23)
        c.drawString(54, H - 74, title)
        c.setFont("Helvetica", 11); c.setFillColor(HexColor("#c7d2fe"))
        c.drawString(54, H - 98, "Executive brief — Northlight Research Group")
        foot(c)
        c.restoreState()

    def later(c, doc):
        c.saveState(); foot(c); c.restoreState()

    def foot(c):
        c.setFont("Helvetica", 8); c.setFillColor(GREY)
        c.drawString(54, 34, "Northlight Research Group")
        c.drawRightString(W - 54, 34, f"{c.getPageNumber()} / 3")

    doc = SimpleDocTemplate(path, pagesize=LETTER, leftMargin=54, rightMargin=54,
                            topMargin=54, bottomMargin=60, title=title)
    h1 = ps("h1", fontName="Helvetica-Bold", fontSize=15.5, leading=19, textColor=HexColor("#312e81"),
            spaceBefore=16, spaceAfter=7)
    body = ps("body", alignment=TA_JUSTIFY, spaceAfter=8)
    stat_num = ps("sn", fontName="Helvetica-Bold", fontSize=24, leading=28, textColor=white,
                  alignment=TA_CENTER)
    stat_lab = ps("sl", fontName="Helvetica", fontSize=8.5, leading=11, textColor=HexColor("#e0e7ff"),
                  alignment=TA_CENTER, spaceBefore=3)
    cw3 = (W - 108 - 24) / 3.0
    cards = Table([[
        [Paragraph("73%", stat_num), Paragraph("of enterprises run agents in production", stat_lab)],
        [Paragraph("4.8×", stat_num), Paragraph("median ROI within the first year", stat_lab)],
        [Paragraph("29 d", stat_num), Paragraph("average time from pilot to production", stat_lab)],
    ]], colWidths=[cw3, cw3, cw3])
    cards.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), INDIGO),
        ("BACKGROUND", (1, 0), (1, 0), VIOLET),
        ("BACKGROUND", (2, 0), (2, 0), HexColor("#6d28d9")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 14), ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    quote_p = Paragraph('"The bottleneck moved from model quality to operational discipline '
                        'in a single budget cycle."',
                        ps("q", fontName="Helvetica-Oblique", fontSize=13, leading=18,
                           textColor=HexColor("#3730a3")))
    attr = Paragraph("— VP Platform Engineering, Fortune 100 retailer",
                     ps("qa", fontSize=9, textColor=GREY, spaceBefore=4))
    quote = Table([[ [quote_p, attr] ]], colWidths=[W - 108 - 6])
    quote.setStyle(TableStyle([
        ("LINEBEFORE", (0, 0), (0, -1), 3.5, VIOLET),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story = [
        Spacer(1, 96),
        Paragraph("Key Findings", h1),
        Paragraph("Our third annual survey covers 412 organizations operating autonomous "
                  "agents across customer operations, engineering, and finance. Three numbers "
                  "define the year:", body),
        Spacer(1, 6), cards, Spacer(1, 14),
        Paragraph("The gap between leaders and laggards is widening. Leaders standardize "
                  "evaluation harnesses and treat prompts as versioned artifacts; laggards "
                  "still ship prompt changes without regression coverage.", body),
        Spacer(1, 8), quote, Spacer(1, 14),
        Paragraph("Deployment Trajectory", h1),
        Paragraph("Active deployments doubled in the trailing twelve months, with growth "
                  "concentrated in mid-market adopters:", body),
        Spacer(1, 6),
        line_chart(),
        Spacer(1, 12),
        Paragraph("What Leaders Do Differently", h1),
        ListFlowable([
            ListItem(Paragraph("Budget for evaluation infrastructure before scaling headcount.", body)),
            ListItem(Paragraph("Route by task value: premium models for revenue paths only.", body)),
            ListItem(Paragraph("Keep humans on exception queues, not approval queues.", body)),
        ], bulletType="bullet", start="•", leftIndent=18),
        Spacer(1, 4),
        Paragraph('Full methodology and cohort definitions: '
                  '<link href="https://northlight.example.org/agents-2026" color="#4f46e5">'
                  '<u>northlight.example.org/agents-2026</u></link>.', body),
    ]
    doc.build(story, onFirstPage=first, onLaterPages=later)

# ================================================================ DOC 5: minimal memo
def doc5():
    path = os.path.join(OUT, "05_memo.pdf")
    doc = SimpleDocTemplate(path, pagesize=LETTER, leftMargin=72, rightMargin=72,
                            topMargin=72, bottomMargin=72, title="Q3 Planning Memo")
    h = ps("h", fontName="Helvetica-Bold", fontSize=14, leading=18, spaceAfter=10)
    meta = ps("m", fontSize=10, textColor=GREY, spaceAfter=2)
    body = ps("b", spaceAfter=8)
    story = [
        Paragraph("Q3 Planning Memo", h),
        Paragraph("From: Operations", meta),
        Paragraph("To: All team leads", meta),
        Paragraph("Date: July 21, 2026", meta),
        Spacer(1, 10),
        HRFlowable(width="100%", thickness=0.8, color=HexColor("#d1d5db"), spaceAfter=12),
        Paragraph("Planning for the third quarter begins next week. Each team should prepare "
                  "a one-page summary covering capacity, dependencies, and the two highest "
                  "leverage initiatives on their roadmap.", body),
        Paragraph("Please note the following deadlines:", body),
        ListFlowable([
            ListItem(Paragraph("August 3 — draft summaries due to operations.", body)),
            ListItem(Paragraph("August 7 — cross-team dependency review.", body)),
            ListItem(Paragraph("August 12 — final plans locked.", body)),
        ], bulletType="bullet", start="•", leftIndent=18),
        Paragraph("Questions should go to the planning channel rather than direct messages "
                  "so answers are shared.", body),
    ]
    doc.build(story)

if __name__ == "__main__":
    for fn in (doc1, doc2, doc3, doc4, doc5):
        fn()
    for f in sorted(os.listdir(OUT)):
        print(f, os.path.getsize(os.path.join(OUT, f)))
