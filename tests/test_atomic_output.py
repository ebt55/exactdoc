"""A failed conversion must not destroy the file it was replacing.

`doc.save(out_path)` wrote straight to the destination, and python-docx
serialises a ZIP incrementally, so any exception partway through left a truncated
file where a good document used to be. The caller asked for a new version and
lost the old one.

Every test here injects a failure at a different stage and asserts the same
thing: **the destination is byte-identical to what it was before.** Injection
rather than mocking the whole path, because the property under test is what
happens when real code raises, and a mock that never raises proves nothing.

    python tests/test_atomic_output.py
"""
import hashlib
import os
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exactdoc import io as xio                    # noqa: E402
from exactdoc.errors import OutputWriteError      # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print("  %-4s %s%s" % ("ok" if cond else "FAIL", name,
                           "" if cond else "   <-- " + detail))
    if not cond:
        FAILED.append(name)


def digest(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def write_docx(path, body=b"<w:document>original</w:document>"):
    """A minimal but structurally valid DOCX."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("_rels/.rels", "<Relationships/>")
        z.writestr("word/document.xml", body)
    return path


def existing_destination(d):
    dest = os.path.join(d, "out.docx")
    write_docx(dest)
    return dest, digest(dest)


# --- the destination survives every stage of failure --------------------------

def test_serialise_failure_preserves_destination():
    with tempfile.TemporaryDirectory() as d:
        dest, before = existing_destination(d)

        def save(tmp):
            with open(tmp, "wb") as f:
                f.write(b"PK\x03\x04 partial...")     # started writing
            raise RuntimeError("figure rasterisation blew up mid-document")

        try:
            xio.publish(save, dest)
            raised = None
        except OutputWriteError as e:
            raised = e
        check("a writer failure raises OutputWriteError", raised is not None)
        check("the destination is byte-identical after a writer failure",
              digest(dest) == before)
        check("the failure names the file as unchanged",
              raised is not None and "unchanged" in raised.message,
              "" if raised is None else raised.message)


def test_invalid_output_never_replaces_a_good_file():
    """The check that matters most: the writer succeeded, and produced rubbish."""
    with tempfile.TemporaryDirectory() as d:
        dest, before = existing_destination(d)

        def save(tmp):
            with open(tmp, "wb") as f:
                f.write(b"this is not a zip file at all")

        try:
            xio.publish(save, dest)
            raised = None
        except OutputWriteError as e:
            raised = e
        check("an unreadable DOCX is refused", raised is not None)
        check("the destination survives an unreadable DOCX",
              digest(dest) == before)


def test_missing_ooxml_member_is_refused():
    with tempfile.TemporaryDirectory() as d:
        dest, before = existing_destination(d)

        def save(tmp):
            with zipfile.ZipFile(tmp, "w") as z:
                z.writestr("[Content_Types].xml", "<Types/>")
                # no word/document.xml: a valid ZIP that is not a document

        try:
            xio.publish(save, dest)
            raised = None
        except OutputWriteError as e:
            raised = e
        check("a ZIP missing word/document.xml is refused", raised is not None)
        check("the failure names the missing member",
              raised is not None and "word/document.xml" in (raised.detail or ""),
              "" if raised is None else str(raised.detail))
        check("the destination survives a structurally invalid DOCX",
              digest(dest) == before)


def test_empty_document_xml_is_refused():
    with tempfile.TemporaryDirectory() as d:
        dest, before = existing_destination(d)

        def save(tmp):
            write_docx(tmp, body=b"   ")

        try:
            xio.publish(save, dest)
            raised = None
        except OutputWriteError as e:
            raised = e
        check("an empty word/document.xml is refused", raised is not None)
        check("the destination survives an empty document body",
              digest(dest) == before)


def test_zero_byte_output_is_refused():
    with tempfile.TemporaryDirectory() as d:
        dest, before = existing_destination(d)

        def save(tmp):
            open(tmp, "wb").close()

        try:
            xio.publish(save, dest)
            raised = None
        except OutputWriteError as e:
            raised = e
        check("a zero-byte output is refused", raised is not None)
        check("the destination survives a zero-byte write",
              digest(dest) == before)


# --- the success path still works, and leaves nothing behind ------------------

def test_success_replaces_and_cleans_up():
    with tempfile.TemporaryDirectory() as d:
        dest, before = existing_destination(d)

        def save(tmp):
            write_docx(tmp, body=b"<w:document>replacement</w:document>")

        out = xio.publish(save, dest)
        check("publish returns the destination", out == os.path.abspath(dest))
        check("the destination was actually replaced", digest(dest) != before)
        check("the replacement is a readable DOCX", not xio.validate_docx(dest),
              str(xio.validate_docx(dest)))
        leftovers = [n for n in os.listdir(d) if n.startswith(".exactdoc-")]
        check("no temp file is left behind on success", not leftovers,
              str(leftovers))


def test_temp_files_are_cleaned_up_on_failure():
    with tempfile.TemporaryDirectory() as d:
        dest, _ = existing_destination(d)

        def save(tmp):
            with open(tmp, "wb") as f:
                f.write(b"partial")
            raise RuntimeError("boom")

        try:
            xio.publish(save, dest)
        except OutputWriteError:
            pass
        leftovers = [n for n in os.listdir(d) if n.startswith(".exactdoc-")]
        check("no temp file is left behind on failure", not leftovers,
              str(leftovers))


def test_temp_file_is_in_the_destination_directory():
    """os.replace is only atomic within a filesystem. A temp file in /tmp
    crossing a mount degrades to a copy -- the non-atomic write this exists to
    prevent."""
    with tempfile.TemporaryDirectory() as d:
        dest = os.path.join(d, "sub", "out.docx")
        seen = {}

        def save(tmp):
            seen["dir"] = os.path.dirname(os.path.abspath(tmp))
            write_docx(tmp)

        xio.publish(save, dest)
        check("the temp file is written beside the destination",
              seen.get("dir") == os.path.dirname(os.path.abspath(dest)),
              "%s != %s" % (seen.get("dir"), os.path.dirname(dest)))
        check("a missing destination directory is created",
              os.path.exists(dest))


def test_publish_to_a_fresh_path_works():
    with tempfile.TemporaryDirectory() as d:
        dest = os.path.join(d, "new.docx")

        def save(tmp):
            write_docx(tmp)

        xio.publish(save, dest)
        check("a first conversion writes normally", os.path.exists(dest))


def test_concurrent_publications_do_not_collide():
    """The refinement loop used a predictable adjacent path (`<dest>.best`), so
    two conversions of the same input in one directory overwrote each other."""
    with tempfile.TemporaryDirectory() as d:
        names = set()
        for i in range(12):
            dest = os.path.join(d, "same.docx")

            def save(tmp, i=i):
                names.add(os.path.basename(tmp))
                write_docx(tmp, body=("<w:document>%d</w:document>" % i).encode())

            xio.publish(save, dest)
        check("every conversion used a distinct temp name", len(names) == 12,
              "%d distinct names for 12 runs" % len(names))


# --- the private workspace ----------------------------------------------------

def test_workspace_is_private_and_removed():
    with xio.Workspace() as ws:
        p = ws.file("candidate.docx")
        write_docx(p)
        path, existed = ws.path, os.path.exists(p)
    check("the workspace holds refinement candidates", existed)
    check("the workspace is removed on exit", not os.path.exists(path))


def test_workspace_is_removed_on_exception():
    path = None
    try:
        with xio.Workspace() as ws:
            path = ws.path
            write_docx(ws.file("candidate.docx"))
            raise RuntimeError("conversion failed mid-refinement")
    except RuntimeError:
        pass
    check("the workspace is removed even when the conversion raises",
          path is not None and not os.path.exists(path))


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print("atomic output: a failed conversion must not destroy its destination\n")
    for t in tests:
        print(t.__name__)
        t()
        print()
    if FAILED:
        print("%d FAILED: %s" % (len(FAILED), ", ".join(FAILED)))
        return 1
    print("all clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
