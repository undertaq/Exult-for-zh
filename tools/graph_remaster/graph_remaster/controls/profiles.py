"""Approved generation-control profiles, independent of runtime backends."""

from __future__ import annotations

from enum import Enum

from ..config import AssetProfile


class AssetType(str, Enum):
    FLAT_TILE = "flat_tile"
    NPC_RLE = "npc_rle"
    BUILDING_COMBO = "building_combo"


_PROFILES = {
    AssetType.FLAT_TILE: AssetProfile(
        name="flat_tile", controls=("canny",), denoise_min=0.05, denoise_max=0.20,
        threshold_low=80, threshold_high=160, atlas_columns=8, atlas_rows=8,
        tile_width=8, tile_height=8,
    ),
    AssetType.NPC_RLE: AssetProfile(
        name="npc_rle", controls=("edge", "silhouette"), denoise_min=0.20, denoise_max=0.40,
        threshold_low=60, threshold_high=140, atlas_columns=1, atlas_rows=1,
        tile_width=8, tile_height=16,
    ),
    AssetType.BUILDING_COMBO: AssetProfile(
        name="building_combo", controls=("canny", "depth"), denoise_min=0.30, denoise_max=0.55,
        threshold_low=100, threshold_high=200, atlas_columns=1, atlas_rows=1,
        tile_width=8, tile_height=8,
    ),
}


def get_profile(asset_type: AssetType | str) -> AssetProfile:
    """Return the immutable approved profile for an extracted asset type."""

    return _PROFILES[AssetType(asset_type)]
