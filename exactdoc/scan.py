"""Conservative, backend-neutral classification for PDFs exactdoc will not convert.

This is a policy check before conversion, not an implementation of the thing it
declines to do.  It uses the parser IR so the PDFium path never needs to import
PyMuPDF, plus one census operation on the backend seam for annotations, which
the IR deliberately does not carry.

Three refusals live here, and they share a shape: **a document whose content is
not the kind of content this converter preserves is refused with a typed error,
never converted into a convincing-looking wrong answer.**

    ocr_required   the text is pixels; we do not invent it
    form           the content is in interactive fields; we do not preserve them
    page cap       the document is longer than the caller has agreed to convert

The first two are properties of the document. The third is a bound, and it is
the only one the caller can answer: `max_pages` lifts it.
"""
from dataclasses import dataclass
import re
from typing import List, Optional

from .errors import InteractiveFormError, OcrRequiredError, PageLimitError
from .input import form_widgets as census_widgets, parse as parse_input
from .model import bbox_area

#: Pages beyond which a single conversion refuses unless `max_pages` says
#: otherwise.  It lives here rather than in `batch.py` because a bound that only
#: existed in batch mode meant the identical 492-page document was refused as one
#: of two files and accepted as one of one -- the same converter answering the
#: same question two ways depending on how it was invoked.  `batch.py` imports it
#: from here so the two limits cannot drift apart again.
MAX_PAGES_PER_DOCUMENT = 250

# --- when is a PDF "a form"? --------------------------------------------------
#
# Measured widget census (PyMuPDF `page.widgets()`), which is the whole basis for
# the two constants below:
#
#     document                       pages  widgets  densest page  form pages
#     y07 IRS Form 1040                  2      199           128           2
#     y14 IRS Form W-9                   6       23            23           1
#     y03 NIST FIPS 197                 46       16             2           0
#     the 16 gated corpus fixtures     1-7        0             0           0
#
# Two things fall out of that table.
#
# **Mean widgets per page is the wrong statistic.** y07 averages 99.5 and y14
# averages 3.83, yet both are fillable forms that convert to garbage -- W-9 is one
# form page followed by five pages of instructions, and the instructions dilute
# the average to below what an ordinary contract would score. Density has to be
# measured per page, not per document.
#
# **A widget is not a form.** y03 is a NIST standard with 16 stray widget
# annotations spread over 46 pages, two at most on any page, and it converts
# perfectly well. A letter with a single signature field is the same case. So the
# threshold has to sit above "an otherwise textual page that happens to carry a
# few fields" and below "a page whose layout *is* fields".
#
# Hence: a page is a form page at 12+ widgets, and the document is a form when
# form pages are at least a tenth of it. The margins on the real evidence are
# comfortable in both directions -- the positives clear 12 by 1.9x (y14) and
# 10.7x (y07); the negatives sit at 2 and 1, six times below it. A one-widget
# signature letter is 12x under the bar and cannot trip this.
FORM_PAGE_WIDGETS = 12
FORM_PAGE_SHARE = 0.10


@dataclass(frozen=True)
class ScanReport:
    classification: str  # digital | mixed | ocr_required | form | blank
    page_count: int
    text_char_count: int
    #: Interactive form widget annotations across the document.
    widget_count: int = 0
    #: Pages carrying at least `FORM_PAGE_WIDGETS` of them.
    form_pages: int = 0
    #: Whether a widget census actually ran.  False means form detection was
    #: skipped, NOT that the document has no widgets -- reporting "0 widgets" for
    #: a backend that cannot count them would be a measurement nobody took.
    census_available: bool = False

    def over_page_cap(self, max_pages: Optional[int] = None) -> bool:
        cap = page_cap(max_pages)
        return cap is not None and self.page_count > cap


def page_cap(max_pages: Optional[int] = None) -> Optional[int]:
    """Resolve the effective page cap.  None means the default, 0 means no cap."""
    if max_pages is None:
        return MAX_PAGES_PER_DOCUMENT
    return None if max_pages == 0 else max_pages


def _normal_chars(ir_page):
    text = "".join(line.text for block in ir_page.blocks for line in block.lines)
    return len(re.sub(r"\s+", "", text))


def _meaningful_visual(page):
    """Whether the page has enough painted coverage to plausibly be a scan.

    A tiny logo, footer rule, or callout is ordinary digital-document baggage;
    none must turn a sparse but selectable PDF into an OCR refusal.  We accept
    raster placement occupying a substantial page region, or unusually dense
    drawing coverage, without using a renderer or importing a backend module.
    """
    area = max(1.0, page.width * page.height)
    if any(bbox_area(image.bbox) >= 0.25 * area for image in page.images):
        return True
    drawing_area = sum(bbox_area(drawing.bbox) for drawing in page.drawings)
    return len(page.drawings) >= 30 and drawing_area >= 0.20 * area


def form_pages(widgets: List[int]) -> int:
    """How many pages are dense enough in widgets to be fillable form pages."""
    return sum(1 for n in widgets if n >= FORM_PAGE_WIDGETS)


def is_form(widgets: Optional[List[int]]) -> bool:
    """Whether interactive form widgets dominate this document.  See above."""
    if not widgets:
        return False
    return form_pages(widgets) >= max(1, FORM_PAGE_SHARE * len(widgets))


def classify_ir(ir, widgets: Optional[List[int]] = None):
    """Classify already-parsed IR; used before ordinary conversion as well.

    `widgets` is the per-page widget census when one is available.  OCR wins the
    `classification` slot over `form` when both apply: a scanned image of a form
    has no recoverable text at all, which is the more fundamental answer, and the
    caller still sees the widget counts alongside it.
    """
    page_chars = [_normal_chars(page) for page in ir.pages]
    total = sum(page_chars)
    visual = [_meaningful_visual(page) for page in ir.pages]
    nonblank = [i for i, page in enumerate(ir.pages)
                if page_chars[i] or visual[i]]
    if not nonblank:
        kind = "blank"
    elif total <= 32 and all(n <= 16 for n in page_chars) and \
            all(visual[i] for i in nonblank):
        # A page with a tiny footer plus an image is still practically a scan.
        kind = "ocr_required"
    elif is_form(widgets):
        kind = "form"
    elif any(n <= 16 and visual[i] for i, n in enumerate(page_chars)) and total:
        kind = "mixed"
    else:
        kind = "digital"
    return ScanReport(kind, len(ir.pages), total,
                      widget_count=sum(widgets or ()),
                      form_pages=form_pages(widgets or []),
                      census_available=widgets is not None)


def inspect_pdf(backend, path):
    """Parse only the IR data needed for a conservative document class."""
    widgets = census_widgets(backend, path)
    return classify_ir(parse_input(backend, path, keep_image_data=False),
                       widgets=widgets)


def preflight(backend, path, max_pages: Optional[int] = None):
    """Refuse a form or an over-long document *before* the full parse.

    The census returns one integer per page, so it answers both questions for the
    price of opening the document and walking its annotations -- no text
    extraction, no images, no paths.  That ordering is the point of a page cap: a
    bound enforced after parsing 492 pages has already spent everything it was
    meant to protect.  Returns the census (or None) so a caller can reuse it.
    """
    widgets = census_widgets(backend, path)
    if widgets is None:
        return None
    if is_form(widgets):
        raise InteractiveFormError(_FORM_MESSAGE)
    cap = page_cap(max_pages)
    if cap is not None and len(widgets) > cap:
        raise PageLimitError(_page_limit_message(len(widgets), cap))
    return widgets


def refusal(report: ScanReport, max_pages: Optional[int] = None):
    """The typed error this scan requires, or None.  One place, three surfaces.

    `--scan-only`, batch and `convert()` used to each decide for themselves what
    a scan meant, which is how the batch runner grew a page limit that the
    single-file path did not have.
    """
    if report.classification == "ocr_required":
        return OcrRequiredError(
            "this PDF appears to require OCR before conversion")
    if report.classification == "form":
        return InteractiveFormError(_FORM_MESSAGE)
    if report.over_page_cap(max_pages):
        return PageLimitError(
            _page_limit_message(report.page_count, page_cap(max_pages)))
    return None


_FORM_MESSAGE = (
    "this PDF is an interactive form: its content lives in fillable fields, "
    "which this converter does not preserve. Converting it would produce a "
    "document that looks like the form and is not one.")


def _page_limit_message(pages, cap):
    return ("this PDF has %d pages, over the %d-page limit. Pass --max-pages "
            "(or max_pages=) to raise it, or 0 to remove it." % (pages, cap))
