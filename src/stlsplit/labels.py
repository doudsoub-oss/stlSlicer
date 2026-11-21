"""Text outlines for engraving.

Phase 7 needs only this part of the module, for the calibration kit's codes (PLAN.md Appendix
E, r10); the layout of piece labels on their faces comes in Phase 8.

Pure: text in, 2D outline out. The font is a path resolved by ``io.resolve_label_font``;
matplotlib reading that file is the one accepted exception to "only ``io`` and ``cli`` touch
the file system" (PLAN.md §3.1). The same text, height and font always give the same outline.
"""

from pathlib import Path

import numpy as np
from manifold3d import CrossSection

from stlsplit import geometry
from stlsplit.config import TEXT_PATH_SIZE


def text_outline(text: str, height: float, font: Path) -> CrossSection:
    """Return a text's outline, centred on the origin.

    Glyphs are flattened at ``TEXT_PATH_SIZE``, then scaled, so their curves stay smooth at a
    few millimetres. TrueType outlines are clockwise, hence the EvenOdd fill rule of
    ``geometry.crosssection_from_contours`` (ADR-0009).

    Args:
        text: The text to draw, with at least one visible glyph.
        height: Height of the text's bounding box, mm (> 0).
        font: The font file.

    Returns:
        The outline in a 2D frame, reading along +x with its top towards +y, mm.

    Raises:
        ValueError: ``height`` isn't positive, or the text draws nothing.
    """
    # Imported here: matplotlib is slow to import and most runs of the CLI don't reach this.
    from matplotlib.font_manager import FontProperties
    from matplotlib.textpath import TextPath

    if height <= 0:
        raise ValueError(f"invalid text height: {height}")
    path = TextPath((0.0, 0.0), text, size=TEXT_PATH_SIZE, prop=FontProperties(fname=font))
    contours = [np.asarray(contour, dtype=np.float64)[:-1] for contour in path.to_polygons()]
    if not contours:
        raise ValueError(f"the text {text!r} draws nothing")
    section = geometry.crosssection_from_contours(contours)
    low_x, low_y, high_x, high_y = section.bounds()
    factor = height / (high_y - low_y)
    centred = section.translate((-(low_x + high_x) / 2, -(low_y + high_y) / 2))
    return centred.scale((factor, factor))
