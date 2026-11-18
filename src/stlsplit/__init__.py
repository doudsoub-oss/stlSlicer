"""stlsplit: split oversized STL models into printable, connectable parts.

See README.md for usage and docs/ARCHITECTURE.md for how the package is organised.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("stlsplit")
except PackageNotFoundError:  # running from a source tree without installing
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
