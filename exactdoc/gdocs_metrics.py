"""Google Docs profile: make substitute fonts occupy the source's width.

Split out of the writer rather than added to it. `docxout` is large, several
concerns already share it, and this is a self-contained pass over a layout that
has just been deep-copied -- so it reads better as one function with its own
tests than as another branch inside `_write_docx`.

The rule itself lives in `fonts.metric_fit`, keyed on measured advance widths.
This module only walks the layout and applies it, once, to every run a document
contains -- body, tables, headers, footers, and the cover band, because a
paragraph that re-wraps inside a header is just as wrong as one in the body.

Applied ONLY under the gdocs output profile. The standard profile keeps the
existing mapping and no tracking, and tests assert its bytes do not move.
"""
from .fonts import metric_fit
from .layout import Cell, DocLayout, FigureEl, ImageEl, Para, RuleEl, TableEl


def _runs_in_para(para, out):
    out.extend(para.runs)
    for row in para.gdocs_rows:
        out.extend(row)


def _runs_in_table(table, out):
    for row in table.rows:
        for cell in row:
            if isinstance(cell, Cell):
                for para in cell.paras:
                    _runs_in_para(para, out)


def _runs_in_element(el, out):
    if isinstance(el, Para):
        _runs_in_para(el, out)
    elif isinstance(el, TableEl):
        _runs_in_table(el, out)


def iter_runs(lay: DocLayout):
    """Every Run a written document will contain, in no particular order."""
    out = []
    for page in lay.pages:
        for chunk in page.chunks:
            for el in chunk.elements:
                _runs_in_element(el, out)
    if lay.cover_band is not None:
        _runs_in_table(lay.cover_band, out)
    for part in (lay.header_default, lay.header_first,
                 lay.footer_default, lay.footer_first):
        if part is None:
            continue
        for el in part.elements:
            _runs_in_element(el, out)
    return out


def apply_metric_fit(lay: DocLayout) -> int:
    """Rewrite run fonts and tracking in place. Returns how many runs moved.

    Mutates, because `_write_docx` has already deep-copied the layout and
    purity is its contract, not this pass's. Tracking is ADDED to whatever a
    run already carries: inference sets `char_spacing` to reproduce TeX's
    inter-word shrink, and that correction and this one describe different
    things about the same run.
    """
    changed = 0
    for run in iter_runs(lay):
        if run.is_tab or not run.text:
            continue
        family, track = metric_fit(run.font, mono=run.mono, serif=run.serif)
        moved = False
        if family != run.font:
            run.font = family
            moved = True
        if track:
            run.char_spacing = run.char_spacing + track * run.size
            moved = True
        changed += 1 if moved else 0
    return changed
