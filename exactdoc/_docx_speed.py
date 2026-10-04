"""Three python-docx hot paths, made fast without changing a byte of output.

The writer spends most of its time inside python-docx, not in exactdoc. On
y06_irs_1040_instructions (126 pages, 27k paragraphs, 213 pictures), profiled
on 2026-10-05, `write_docx` took 58.6s under cProfile and two python-docx
internals accounted for 20.3s of it:

    StoryPart.next_id              8.0s   213 calls, 37ms each
    BaseOxmlElement
      .first_child_found_in       12.3s   402k calls

and the refine loop writes the document once per round, so a product
conversion of y06 paid both four times. Both are replaced here by functions
that return exactly what the originals return; the proof is that `word/*.xml`
of every corpus document is byte-identical with and without them
(docs/evidence/refine-speed-2026-10-05.json) and the equivalence tests in
tests/test_docx_speed.py.

**next_id.** python-docx gives each new picture the id `max(every @id in the
part) + 1`, found by an XPath over the whole part -- quadratic in a long,
picture-heavy document. In a document exactdoc writes, ids only ever come
from that same call (`run.add_picture` is the only path that creates an
unprefixed `id` attribute: the docPr it inserts carries the new id and its
pic:cNvPr carries 0), and no element holding one is removed afterwards. So
after the first scan the maximum is the id just handed out, and the next one
is that plus one. The shortcut is taken only for packages `enable_monotonic_ids`
has marked -- the ones `docxout._write_docx` creates -- and every other
python-docx document in the process keeps the original scan.

**first_child_found_in.** The original asks `find(qn(tag))` once per possible
successor, in priority order: for a run's properties that is up to ~35 tag
names, each through `qn`, to place one element. This returns the same element
-- the first child in document order whose tag is the earliest of `tagnames`
to occur -- from one pass over the children and a cached tuple of Clark names.
It is a pure function of the element and its arguments, so installing it for
the whole process is safe.

**CT_R.clear_content** (1.9s of XPath per y06 write) is the third: the same
removal, done by a loop over the run's children instead of an XPath per run.
"""
from docx.oxml.ns import qn
from docx.oxml.text.run import CT_R
from docx.oxml.xmlchemy import BaseOxmlElement
from docx.parts.story import StoryPart

_ORIGINAL_FIRST_CHILD = BaseOxmlElement.first_child_found_in
_ORIGINAL_NEXT_ID = StoryPart.next_id
_ORIGINAL_CLEAR_RUN = CT_R.clear_content
_RPR = qn("w:rPr")
_CLARK = {}
_MARK = "_exactdoc_monotonic_ids"
# Which strategy answers fastest, measured with timeit on lxml 6.1 / CPython
# 3.12 (2026-10-05): one Python pass over the children wins once there are more
# than four names to try and at most sixteen children -- a run's or a
# paragraph's properties -- and loses badly on long child lists. Both
# strategies return the same element; only speed depends on these.
_FEW_NAMES = 4
_MANY_CHILDREN = 16


def _first_child_found_in(self, *tagnames):
    """First child whose tag is the earliest of `tagnames` present, or None.

    Same answer as python-docx's: `find` returns the first matching child in
    document order, and the tag names are tried in the order given.
    """
    clark = _CLARK.get(tagnames)
    if clark is None:
        clark = _CLARK[tagnames] = tuple(qn(t) for t in tagnames)
    if len(clark) <= _FEW_NAMES or len(self) > _MANY_CHILDREN:
        # Few names, or a long child list (w:body holds every paragraph, and
        # its one successor is w:sectPr): lxml's C-level `find` per name beats
        # a Python pass over thousands of children. The original's own loop,
        # minus a `qn` per call.
        for name in clark:
            child = self.find(name)
            if child is not None:
                return child
        return None
    # The nearest successor is often present, and then one C-level probe
    # answers -- as fast as the original at its best.
    child = self.find(clark[0])
    if child is not None:
        return child
    first = {}
    for child in self:
        tag = child.tag
        if tag not in first:
            first[tag] = child
    if not first:
        return None
    for name in clark:
        child = first.get(name)
        if child is not None:
            return child
    return None


def _clear_run_content(self):
    """Remove every child element but a w:rPr -- python-docx's `clear_content`.

    The original evaluates the XPath `./*[not(self::w:rPr)]` on every
    `run.text = ...`, which the writer does once per run (39,661 times on
    y06, 1.9s of XPath for runs that hold nothing yet). `./*` is the element
    children, comments and processing instructions excluded, which is what
    the string-tag test keeps.
    """
    for child in list(self):
        tag = child.tag
        if isinstance(tag, str) and tag != _RPR:
            self.remove(child)


def _next_id(self):
    package = self.package
    if not getattr(package, _MARK, False):
        return _ORIGINAL_NEXT_ID.fget(self)
    last = self.__dict__.get("_exactdoc_last_id")
    nid = _ORIGINAL_NEXT_ID.fget(self) if last is None else last + 1
    self.__dict__["_exactdoc_last_id"] = nid
    return nid


def enable_monotonic_ids(document):
    """Mark a python-docx Document whose picture ids only ever grow.

    Every story part in its package -- body, headers, footers -- then hands
    out picture ids without rescanning the part. Only for documents built the
    way docxout builds them: no element carrying an id is ever removed.
    """
    setattr(document.part.package, _MARK, True)
    return document


def install():
    BaseOxmlElement.first_child_found_in = _first_child_found_in
    StoryPart.next_id = property(_next_id, doc=_ORIGINAL_NEXT_ID.__doc__)
    CT_R.clear_content = _clear_run_content


def uninstall():
    """Restore python-docx's own implementations (tests compare the two)."""
    BaseOxmlElement.first_child_found_in = _ORIGINAL_FIRST_CHILD
    StoryPart.next_id = _ORIGINAL_NEXT_ID
    CT_R.clear_content = _ORIGINAL_CLEAR_RUN


install()
