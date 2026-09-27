from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


SCRIPT = Path(__file__).with_name("generate_full_reference_design.py")


@pytest.fixture
def reference_builder(monkeypatch):
    soundfile = ModuleType("soundfile")
    soundfile.info = lambda path: SimpleNamespace(samplerate=24000, channels=1, frames=72000)
    opencc = ModuleType("opencc")

    class OpenCC:
        def __init__(self, _config: str):
            pass

        def convert(self, text: str) -> str:
            return text

    opencc.OpenCC = OpenCC
    breeze_infer = ModuleType("breeze_infer")
    breeze_infer.__path__ = []
    runtime = ModuleType("breeze_infer.runtime")
    runtime.load_runtime = lambda *args, **kwargs: None
    runtime.set_all_seeds = lambda *args, **kwargs: None
    runtime.update_generation_config_for_breeze = lambda *args, **kwargs: None
    templates = ModuleType("breeze_infer.templates")
    templates.get_template = lambda *args, **kwargs: None
    templates.prepare_inputs = lambda *args, **kwargs: None
    models = ModuleType("models")
    models.__path__ = []
    fast_streaming = ModuleType("models.fast_streaming")
    fast_streaming.FastBreezeStreamingRuntime = type("FastBreezeStreamingRuntime", (), {})
    fast_streaming.FastStreamingConfig = type("FastStreamingConfig", (), {})
    for name, module in {
        "soundfile": soundfile,
        "opencc": opencc,
        "breeze_infer": breeze_infer,
        "breeze_infer.runtime": runtime,
        "breeze_infer.templates": templates,
        "models": models,
        "models.fast_streaming": fast_streaming,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    spec = importlib.util.spec_from_file_location("u6_reference_builder_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_provisional_designs_are_labeled_and_unverified_links_are_omitted(
    reference_builder, monkeypatch, tmp_path: Path
) -> None:
    module = reference_builder
    root = tmp_path / "project"
    review = root / "u6_voice" / "review"
    review.mkdir(parents=True)
    catalog = root / "u6_voice" / "u6_npc_voice_designs.json"
    catalog.parent.mkdir(parents=True, exist_ok=True)
    catalog.write_text(json.dumps({"designs": {
        "u6_rowan_provisional_cb6": {
            "npc": "Rowan",
            "npcs": ["Rowan"],
            "voice_desc_en": "An adult female fantasy voice, composed and deliberate.",
            "voice_desc_zh": "成年女性奇幻聲線，沉著而果斷。",
            "ref_en_text": "Justice must be weighed with care. Let truth guide every judgment.",
            "ref_zh_text": "正義必須謹慎衡量。讓真相引導每一次裁決。",
            "u6_description": "Undocumented internal active-face actor for the Justice mantra.",
            "u6_description_source": "Compiled Ultima VI usecode 0x0CB6; provisional casting context",
            "casting_inference": {"gender": "female", "age": "adult", "role": "justice mantra speaker"},
            "casting_status": "provisional",
            "casting_assumption": "Female casting is a temporary voice-design choice; game sources do not confirm gender.",
            "casting_evidence": "Actor ID 251 is selected as the active face before the Justice mantra line.",
            "provisional_reason": "No reliable gender, portrait, or character description was found.",
        },
    }}), encoding="utf-8")
    monkeypatch.setattr(module, "ROOT", root)
    monkeypatch.setattr(module, "OUT", review)
    monkeypatch.setattr(module, "CATALOG", catalog)
    monkeypatch.setattr(module, "PORTRAIT_MAP", review / "portrait_map.json")
    monkeypatch.setattr(module, "_shared_reference_voices", lambda: [])

    rows = module._load_manifest()
    module._write_review(rows, completed=0, total=len(rows))
    page = (review / "index.html").read_text(encoding="utf-8")
    metadata = json.loads((review / "metadata.json").read_text(encoding="utf-8"))

    assert len(rows) == 2
    assert {row["casting_status"] for row in rows} == {"provisional"}
    assert {row["wiki_url"] for row in rows} == {""}
    assert "PROVISIONAL CASTING — REVIEW BEFORE CLONING" in page
    assert "Female casting is a temporary voice-design choice" in page
    assert "No reliable gender, portrait, or character description was found." in page
    assert 'href="https://wiki.ultimacodex.com/wiki/Rowan"' not in page
    assert all(row["casting_status"] == "provisional" for row in metadata["rows"])
