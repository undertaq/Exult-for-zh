"""Approved generation-control profiles, independent of runtime backends."""

from __future__ import annotations

from dataclasses import replace
from enum import Enum
from typing import Iterable

from ..config import AssetProfile, canonical_asset_profile


class AssetType(str, Enum):
    FLAT_TILE = "flat_tile"
    NPC_RLE = "npc_rle"
    BUILDING_COMBO = "building_combo"


def infer_asset_type(width: int, height: int, frame_count: int) -> AssetType:
    """Infer a safe default profile when extraction lacks explicit type metadata.

    The extractor knows shape geometry and animation cardinality even when the
    source archive does not carry semantic labels. A lone canonical 8x8 cell
    is a flat tile; animated shapes are NPC/RLE candidates; other single-frame
    shapes are building composites. Explicit metadata remains authoritative.
    """

    if width < 1 or height < 1 or frame_count < 1:
        raise ValueError("asset dimensions and frame_count must be positive")
    if frame_count > 1:
        return AssetType.NPC_RLE
    if (width, height) == (8, 8):
        return AssetType.FLAT_TILE
    return AssetType.BUILDING_COMBO


def get_profile(asset_type: AssetType | str) -> AssetProfile:
    """Return the immutable approved profile for an extracted asset type."""

    return canonical_asset_profile(AssetType(asset_type).value)


def profile_with_controls(
    asset_type: AssetType | str, controls: Iterable[str]
) -> AssetProfile:
    """Return a profile with a validated, explicit subset of its controls."""

    profile = get_profile(asset_type)
    requested = tuple(controls)
    if not requested:
        raise ValueError("controls override must not be empty")
    unsupported = tuple(kind for kind in requested if kind not in profile.controls)
    if unsupported:
        raise ValueError(
            f"unsupported controls for {profile.name!r}: {', '.join(unsupported)}"
        )
    return replace(profile, controls=requested)
