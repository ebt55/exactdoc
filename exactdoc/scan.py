"""Conservative, backend-neutral classification for OCR-required PDFs.

This is a policy check before conversion, not an OCR implementation.  It uses
the parser IR so the PDFium path never needs to import PyMuPDF.
"""
from dataclasses import dataclass
import re

from .input import parse as parse_input
from .model import bbox_area


@dataclass(frozen=True)
class ScanReport:
    classification: str  # digital | mixed | ocr_required | blank
    page_count: int
    text_char_count: int


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


def classify_ir(ir):
    """Classify already-parsed IR; used before ordinary conversion as well."""
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
    elif any(n <= 16 and visual[i] for i, n in enumerate(page_chars)) and total:
        kind = "mixed"
    else:
        kind = "digital"
    return ScanReport(kind, len(ir.pages), total)


def inspect_pdf(backend, path):
    """Parse only the IR data needed for a conservative document class."""
    return classify_ir(parse_input(backend, path, keep_image_data=False))
