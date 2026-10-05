"""Worker for _pagelines_pool: `python -m exactdoc._pagelines_worker PDF START STOP`.

Writes the pickled lines of pages [START, STOP) to stdout and nothing else.
"""
import pickle
import sys


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    path, start, stop = argv[0], int(argv[1]), int(argv[2])
    import logging
    logging.getLogger("pypdfium2").setLevel(logging.ERROR)
    from .parse_pdfium import page_lines_range
    lines = page_lines_range(path, start, stop)
    out = sys.stdout.buffer
    out.write(pickle.dumps(lines, pickle.HIGHEST_PROTOCOL))
    out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
