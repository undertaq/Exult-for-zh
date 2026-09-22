import json
import sys
from pathlib import Path
from types import SimpleNamespace

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
for site_packages in (SCRIPT_DIR / ".venv" / "lib").glob("python*/site-packages"):
    sys.path.insert(0, str(site_packages))

import audit_omnivoice_zh as audit


def test_build_corpus_deduplicates_text_and_keeps_all_sources(tmp_path):
    mapping = tmp_path / "mapping.json"
    designs = tmp_path / "designs.json"
    mapping.write_text(json.dumps([
        {"npc": "A", "zh_text": "傳說", "zh_func_id": "0401", "zh_output_filename": "a.ogg"},
        {"npc": "B", "zh_text": "傳說", "zh_func_id": "0402", "zh_output_filename": "b.ogg"},
    ]), encoding="utf-8")
    designs.write_text(json.dumps({"designs": {
        "voice_a": {"npc": "A", "ref_zh_text": "傳說"},
        "voice_c": {"npcs": ["C"], "ref_zh_text": "銀行行長"},
    }}), encoding="utf-8")

    corpus = audit.build_corpus(mapping, designs)

    assert [item["source_text"] for item in corpus] == ["傳說", "銀行行長"]
    assert [source["kind"] for source in corpus[0]["sources"]] == ["mapping", "mapping", "design"]
    assert corpus[0]["sources"][0] == {
        "kind": "mapping", "npc": "A", "function": "0401", "output": "a.ogg",
        "row_index": 0, "row_key": "A:0401:::a.ogg",
    }
    assert corpus[0]["sources"][2]["design_id"] == "voice_a"


def test_mine_candidates_is_deterministic_and_deduplicates_candidate_key():
    corpus = [{
        "source_text": "銀行行長",
        "sources": [{"kind": "mapping", "npc": "Britannian", "function": "1234", "output": "x.ogg"}],
    }]

    first = audit.mine_candidates(corpus)
    second = audit.mine_candidates(corpus)

    assert first == second
    keys = [(c["source_text"], c["character"], c["word_context"]) for c in first]
    assert len(keys) == len(set(keys))
    assert any(c["character"] == "行" and len(c["candidate_readings"]) > 1 for c in first)
    assert all(c["source_text"] == "銀行行長" for c in first)


def test_repeated_candidate_key_retains_every_occurrence():
    corpus = [{"source_text": "行行行", "sources": []}]

    candidate = next(c for c in audit.mine_candidates(corpus) if c["character"] == "行")

    assert [item["position"] for item in candidate["occurrences"]] == [0, 1, 2]
    assert len({item["pinyin_control_text"] for item in candidate["occurrences"]}) == 3
    assert all(set(item) >= {"position", "word_context", "expected_reading", "pinyin_control_text"}
               for item in candidate["occurrences"])


def test_confirmed_overrides_have_exact_phrase_and_language_scope():
    rules = [{"lang": "zh", "source": "偽先知", "tts": "WEI4先知"}]

    assert audit.apply_confirmed_overrides("那個偽先知來了", "zh", rules) == "那個WEI4先知來了"
    assert audit.apply_confirmed_overrides("偽先知", "en", rules) == "偽先知"
    assert audit.apply_confirmed_overrides("偽善先知", "zh", rules) == "偽善先知"


def test_confirmed_rule_replaces_mainland_candidate_control():
    candidate = {
        "source_text": "他是偽先知。", "character": "偽",
        "pinyin_control_text": "他是WEI3先知。", "expected_reading": "wei3",
    }
    rule = {
        "lang": "zh", "source": "偽先知", "tts": "WEI4先知",
        "expected_pinyin": "wèi xiān zhī",
    }

    audit.apply_confirmed_candidate_rules([candidate], [rule])

    assert candidate["pinyin_control_text"] == "他是WEI4先知。"
    assert candidate["expected_reading"] == "wèi"
    assert candidate["confirmed_rule"] == rule


def test_review_record_has_three_variants_and_only_pinyin_is_adoptable(tmp_path):
    candidate = {
        "id": "candidate-1", "source_text": "偽先知", "simplified_text": "伪先知",
        "character": "偽", "word_context": "偽先知", "expected_reading": "wei4",
        "candidate_readings": ["wei3", "wei4"], "reasons": ["traditional_simplified"],
        "sources": [{"kind": "mapping", "npc": "X", "function": "12", "output": "12.ogg"}],
        "pinyin_control_text": "WEI4先知",
    }

    record = audit.build_review_records([candidate], tmp_path)[0]

    assert record["status"] == "unreviewed"
    assert [v["kind"] for v in record["variants"]] == ["traditional", "simplified", "pinyin_control"]
    assert [v["eligible_for_adoption"] for v in record["variants"]] == [False, False, True]
    assert all("audio" in variant and "tts_text" in variant for variant in record["variants"])
    assert record["source_text"] == "偽先知"
    assert record["expected_reading"] == "wei4"


def test_write_audit_emits_self_contained_html_and_jsonl_export(tmp_path):
    payload = {"candidates": []}
    audit.write_audit(tmp_path, payload)

    assert json.loads((tmp_path / "pronunciation_candidates.json").read_text(encoding="utf-8")) == payload
    page = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "pronunciation_candidates.json" not in page
    assert "Export JSONL" in page
    assert "pass" in page and "failed" in page and "unreviewed" in page
    assert 'id="search"' in page
    assert "PAGE_SIZE" in page
    for filter_id in ("reason-filter", "character-filter", "source-filter", "status-filter",
                      "audio-filter", "adoption-filter"):
        assert f'id="{filter_id}"' in page
    for field in ("selected_variant", "review_reason", "reviewer_note", "selected_tts_text",
                  "corrected_reading", "sources"):
        assert field in page


def test_write_audit_escapes_jsonl_newlines_for_browser_javascript(tmp_path):
    audit.write_audit(tmp_path, {"candidates": []})

    page = (tmp_path / "index.html").read_text(encoding="utf-8")

    assert "join('\\n')" in page
    assert "join('\n')" not in page


class FakeAudioBackend:
    def __init__(self):
        self.rendered = []
        self.model_loads = 0

    def load_model(self, gpu, model):
        self.model_loads += 1
        return object()

    def complete(self, output, job):
        return output.is_file() and output.with_suffix(".json").is_file()

    def render(self, model, job, prompt_cache):
        self.rendered.append(job.tts_text)
        return ([0.1, 0.2], 24000, 7), job.tts_text

    def publish(self, job, audio, sample_rate, seed, args, rendered_text):
        job.output.parent.mkdir(parents=True, exist_ok=True)
        job.output.write_bytes(b"OggS")
        job.output.with_suffix(".json").write_text(json.dumps({
            "status": "generated", "tts_text": job.tts_text,
        }), encoding="utf-8")


def test_generate_audio_is_bounded_writes_ogg_metadata_and_resumes(tmp_path):
    record = {
        "id": "candidate-1", "source_text": "偽先知",
        "sources": [{"kind": "mapping", "npc": "X", "function": "12", "output": "12.ogg",
                     "row_index": 0, "row_key": "X:12:::12.ogg"}],
        "variants": [
            {"kind": "traditional", "tts_text": "偽先知", "eligible_for_adoption": False},
            {"kind": "simplified", "tts_text": "伪先知", "eligible_for_adoption": False},
            {"kind": "pinyin_control", "tts_text": "WEI4先知", "eligible_for_adoption": True},
        ],
    }
    clone = SimpleNamespace(
        npc="X", lang="zh", text="偽先知", output=Path("12.ogg"), tts_text="偽先知",
        override_revision=None, design_id="voice_x", ref_audio=tmp_path / "ref.ogg",
        ref_text="參考", func_id="12", offset_key="", segment=0,
    )
    clone.ref_audio.write_bytes(b"ref")
    backend = FakeAudioBackend()

    audit.generate_selected_audio(
        [record], ["candidate-1"], 1, tmp_path, gpu=2,
        clone_jobs=[clone], backend=backend, model_id="fake/model",
    )
    audit.generate_selected_audio(
        [record], ["candidate-1"], 1, tmp_path, gpu=2,
        clone_jobs=[clone], backend=backend, model_id="fake/model",
    )

    assert backend.rendered == ["偽先知", "伪先知", "WEI4先知"]
    assert backend.model_loads == 1
    assert all(variant["audio"].endswith(".ogg") for variant in record["variants"])
    assert all(variant["audio_status"] == "generated" for variant in record["variants"])
    metadata = json.loads((tmp_path / "audio" / "candidate-1.pinyin_control.json").read_text())
    assert metadata["candidate_id"] == "candidate-1"
    assert metadata["variant"] == "pinyin_control"
    assert metadata["eligible_for_adoption"] is True


def test_generate_audio_rejects_unbounded_or_unknown_selection(tmp_path):
    try:
        audit.generate_selected_audio([], [], 0, tmp_path, gpu=0, clone_jobs=[], backend=FakeAudioBackend())
    except ValueError as error:
        assert "positive" in str(error)
    else:
        raise AssertionError("unbounded generation was accepted")


def test_generate_audio_records_missing_clone_as_variant_errors(tmp_path):
    record = {
        "id": "missing", "source_text": "沒有來源", "sources": [],
        "variants": [{"kind": kind, "tts_text": "沒有來源", "eligible_for_adoption": kind == "pinyin_control"}
                     for kind in ("traditional", "simplified", "pinyin_control")],
    }

    audit.generate_selected_audio(
        [record], ["missing"], 1, tmp_path, gpu=0, clone_jobs=[], backend=FakeAudioBackend()
    )

    assert all(variant["audio_status"] == "error" for variant in record["variants"])
    assert all(variant["audio_metadata"]["status"] == "error" for variant in record["variants"])
    assert len(list((tmp_path / "audio").glob("missing.*.json"))) == 3
