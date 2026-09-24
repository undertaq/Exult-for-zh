from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
import generate_breeze_u6 as module

from generate_breeze_u6 import (
    _catalog_gender,
    _load_reference_catalog,
    avatar_genders_for_route,
    narrator_reference_id,
    route_voice_parts,
)


def test_narrator_reference_matches_active_speaker_gender() -> None:
    assert narrator_reference_id("male") == "npc_narrator_male"
    assert narrator_reference_id("female") == "npc_unknown"


def test_mixed_usecode_line_keeps_narrator_and_speaker_parts() -> None:
    parts = route_voice_parts("Maldric says @Hello, old friend!@ He smiles.", "Maldric 說@老朋友，你好！@ 他微笑。", "en")
    assert parts == [
        ("narrator", "Maldric says"),
        ("speaker", "Hello, old friend!"),
        ("narrator", "He smiles."),
    ]


def test_avatar_route_expands_to_both_genders() -> None:
    assert avatar_genders_for_route("Avatar", routed=True) == ("male", "female")
    assert avatar_genders_for_route("Dupre", routed=True) == (None,)
    assert avatar_genders_for_route("Avatar", routed=False) == (None,)


def test_gargoyle_pronouns_resolve_male_instead_of_nonhuman_female_fallback() -> None:
    description = "a small gargoyle child. He speaks to you and his father is Valkadesh."
    assert _catalog_gender(description, "female") == "male"


def test_beh_lem_uses_male_route_gender() -> None:
    _, genders = _load_reference_catalog()
    assert genders["beh lem"] == "male"


def test_reference_metadata_gender_overrides_stale_design_inference() -> None:
    _, genders = _load_reference_catalog()
    assert genders["andreas"] == "male"


def test_beh_lem_english_output_is_peak_normalized() -> None:
    job = SimpleNamespace(target_npc="Beh Lem", lang="en")
    assert hasattr(module, "normalize_audio_for_job")
    normalized = module.normalize_audio_for_job(job, np.array([-0.1, 0.05], dtype=np.float32))
    assert float(np.max(np.abs(normalized))) == pytest.approx(10 ** (-1 / 20), abs=1e-6)
