"""Authoritative alpha-mask restoration for generated artwork."""

from __future__ import annotations

from PIL import Image


def restore_source_alpha(candidate: Image.Image, source_mask: Image.Image) -> Image.Image:
    """Return candidate RGB with source alpha substituted byte-for-byte.

    ``putalpha`` deliberately changes only the alpha channel.  In particular,
    RGB values in transparent pixels remain available to human review tools.
    """

    if candidate.size != source_mask.size:
        raise ValueError("candidate and source mask dimensions must match")
    restored = candidate.convert("RGBA")
    restored.putalpha(source_mask.convert("L"))
    return restored
