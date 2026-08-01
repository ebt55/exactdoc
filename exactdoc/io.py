"""Publish a DOCX, or leave the destination exactly as it was.

`doc.save(out_path)` writes straight to the destination. python-docx serialises a
ZIP incrementally, so an exception partway through -- a figure that fails to
rasterise, a full disk, a cancelled run -- leaves a truncated file where a
perfectly good conversion used to be. The caller asked for a new version of a
document and lost the old one.

The refinement loop made it worse. It wrote candidates to a *predictable*
adjacent path (`<name>.best`), so two conversions of the same input in the same
directory raced each other, and a crash left the intermediate lying around
looking like output.

So publication is transactional:

    1. serialise into a unique temp file IN THE DESTINATION DIRECTORY
    2. close the document and every native handle first
    3. validate the bytes as a ZIP carrying the required OOXML members
    4. flush and fsync so the rename cannot expose a partial file
    5. os.replace onto the destination -- atomic on POSIX and on Windows
    6. remove temp state in `finally`, whatever happened

Same directory matters: `os.replace` is only atomic within a filesystem, and a
temp file in /tmp crossing onto another mount degrades to a copy, which is
precisely the non-atomic write this module exists to prevent.

Validation before replacement matters just as much. An unreadable DOCX that
replaced a readable one is not better than a failed conversion, and the writer
cannot always tell that it produced one.
"""
import os
import tempfile
import zipfile

from .errors import OutputWriteError

# The members every DOCX must carry to be openable at all. Word, LibreOffice and
# Google Docs disagree about a great deal; they agree about these.
REQUIRED_MEMBERS = ("[Content_Types].xml", "word/document.xml", "_rels/.rels")


def validate_docx(path):
    """-> [problem, ...]. Empty means the file is a structurally sound DOCX.

    Deliberately structural rather than semantic: this is the last check before
    a file replaces a good one, so it answers "can this be opened?" and leaves
    "is this laid out well?" to the fidelity gate.
    """
    problems = []
    try:
        size = os.path.getsize(path)
    except OSError as e:
        return ["cannot stat the written file: %s" % e.strerror]
    if size <= 0:
        return ["the written file is empty"]
    try:
        with zipfile.ZipFile(path) as z:
            bad = z.testzip()
            if bad is not None:
                problems.append("corrupt ZIP member: %s" % bad)
            names = set(z.namelist())
            for member in REQUIRED_MEMBERS:
                if member not in names:
                    problems.append("missing required OOXML member: %s" % member)
            if "word/document.xml" in names:
                try:
                    if not z.read("word/document.xml").strip():
                        problems.append("word/document.xml is empty")
                except (KeyError, zipfile.BadZipFile, OSError) as e:
                    problems.append("word/document.xml unreadable: %s" % e)
    except zipfile.BadZipFile as e:
        problems.append("not a readable ZIP archive: %s" % e)
    except OSError as e:
        problems.append("cannot read the written file: %s" % e.strerror)
    return problems


def _fsync(fh):
    """Best effort. A platform without fsync is not a reason to fail a write."""
    try:
        fh.flush()
        os.fsync(fh.fileno())
    except (OSError, AttributeError, ValueError):
        pass


def publish(save, dest, validate=True):
    """Run `save(tmp_path)`, validate, then atomically replace `dest`.

    `save` is a callable taking the path to write, rather than an already-written
    file, so that nothing is ever serialised to the destination. A caller holding
    a python-docx Document passes `doc.save`.

    Raises OutputWriteError, having left `dest` untouched, if serialising fails,
    if the result is not a sound DOCX, or if the replacement itself fails.
    """
    dest = os.path.abspath(dest)
    d = os.path.dirname(dest) or "."
    try:
        os.makedirs(d, exist_ok=True)
    except OSError as e:
        raise OutputWriteError(
            "cannot create the output directory", detail=e.strerror)

    # Unique, and in the destination directory: same filesystem, and no
    # predictable name for a concurrent conversion to collide with.
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".exactdoc-", suffix=".docx")
    os.close(fd)
    try:
        try:
            save(tmp)
        except Exception as e:
            raise OutputWriteError(
                "the document could not be serialised; %s is unchanged"
                % os.path.basename(dest),
                detail="%s: %s" % (type(e).__name__, e))

        if validate:
            problems = validate_docx(tmp)
            if problems:
                raise OutputWriteError(
                    "the converter produced an unreadable DOCX; %s is unchanged"
                    % os.path.basename(dest),
                    detail="; ".join(problems))

        # Durability before visibility: a rename that exposes an unflushed file
        # can survive a crash as a valid name pointing at partial bytes.
        try:
            with open(tmp, "rb+") as fh:
                _fsync(fh)
        except OSError:
            pass

        try:
            os.replace(tmp, dest)
        except OSError as e:
            raise OutputWriteError(
                "could not replace %s; it is unchanged" % os.path.basename(dest),
                detail=e.strerror)
        tmp = None                      # published; nothing left to clean up
        return dest
    finally:
        if tmp is not None and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


class Workspace:
    """A private scratch directory for one conversion.

    Refinement candidates belong here rather than beside the destination. The
    loop used to write `<dest>.best`, which is a predictable path: two
    conversions of the same input in the same directory overwrote each other's
    candidates, and a crash left the file behind looking like a deliverable.

    Removed on exit, including on exception. Failure to clean up is not raised:
    losing a temp directory is worse than losing the conversion's result only if
    the result was already lost.
    """

    def __init__(self, prefix="exactdoc-"):
        self._prefix = prefix
        self.path = None

    def __enter__(self):
        self.path = tempfile.mkdtemp(prefix=self._prefix)
        return self

    def file(self, name):
        return os.path.join(self.path, name)

    def __exit__(self, *exc):
        import shutil
        if self.path:
            shutil.rmtree(self.path, ignore_errors=True)
        self.path = None
        return False
