# Security policy

## Reporting a vulnerability

**Please do not open a public issue for a security problem.** Report it
privately through GitHub:
[Security → Report a vulnerability](https://github.com/ebt55/exactdoc/security/advisories/new).
Only the maintainer can read the report, and the fix and advisory are prepared
in private before anything is published.

Include what you can of: the exactdoc version (`exactdoc --version`), the
command or API call, and a way to reproduce it. If the problem needs a crafted
PDF, attach it to the private report, never to a public issue.

exactdoc is maintained by one person. Expect an acknowledgement within about a
week; a fix depends on the problem.

## What counts

exactdoc reads untrusted files, so these are in scope:

- a PDF that makes exactdoc write outside the output path it was given, run
  code, or read files it was not asked to;
- a PDF that makes a conversion use unbounded memory, disk or time beyond the
  documented limits (the page cap, `--max-pages`);
- anything that sends a document, or part of one, off the machine without
  `--allow-cloud-upload` (conversion is local by design; see the README);
- a DOCX written by exactdoc that is unsafe to open in Word, LibreOffice or
  Google Docs.

PDF parsing is done by PDFium through `pypdfium2`. A flaw inside PDFium itself
is best reported to the [PDFium project](https://pdfium.googlesource.com/pdfium/)
as well; tell us too, so the minimum `pypdfium2` version can move.

## Supported versions

Fixes go into the newest release on PyPI. exactdoc is pre-1.0, and earlier
pre-releases are not patched.
