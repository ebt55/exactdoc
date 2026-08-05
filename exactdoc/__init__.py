"""exactdoc -- measurement-driven PDF to DOCX conversion.

    from exactdoc import convert
    convert("paper.pdf", "paper.docx")

The public surface is deliberately small: `convert`, the options profile that
supplies its defaults, and `__version__`. That is what 1.0.0 commits to.
Everything else is internal and may move in a minor release -- the parser seam,
the inference thresholds and the writer's profile constants are all measured
values that move when a measurement moves.

Names resolve lazily (PEP 562) so that `import exactdoc` costs nothing but this
docstring. It also lets an explicitly selected candidate reach the backend seam
before importing the shipping parser.
"""
__all__ = ["convert", "ConversionOptions", "PRODUCT", "RAW", "__version__"]


def _version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:                                  # pragma: no cover
        return "0.0.0+unknown"
    try:
        return version("exactdoc")
    except PackageNotFoundError:
        # Running from a checkout that was never installed -- the normal state
        # for the harness. Say so rather than inventing a number that would
        # then be published in an evidence artifact.
        return "0.0.0+source"


__version__ = _version()


def __getattr__(name):
    if name == "convert":
        from .convert import convert
        return convert
    if name in ("ConversionOptions", "PRODUCT", "RAW"):
        from . import options
        return getattr(options, name)
    raise AttributeError("module %r has no attribute %r" % (__name__, name))


def __dir__():
    return sorted(__all__)
