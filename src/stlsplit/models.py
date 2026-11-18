"""Data model shared by every pipeline stage (PLAN.md §5.2).

Phase 0 defines only ``Axis``; the dataclasses are added in Phase 1.
"""

from typing import Literal

Axis = Literal[0, 1, 2]
"""Axis index in the cutting frame: 0 = X, 1 = Y, 2 = Z."""
