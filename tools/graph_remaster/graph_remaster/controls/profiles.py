"""Approved generation-control profiles, independent of runtime backends."""

from __future__ import annotations

from enum import Enum

from ..config import AssetProfile, canonical_asset_profile


class AssetType(str, Enum):
    FLAT_TILE = "flat_tile"
    NPC_RLE = "npc_rle"
    BUILDING_COMBO = "building_combo"


def get_profile(asset_type: AssetType | str) -> AssetProfile:
    """Return the immutable approved profile for an extracted asset type."""

    return canonical_asset_profile(AssetType(asset_type).value)
