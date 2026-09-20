import json
import sys
from pathlib import Path

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
        "kind": "mapping", "npc": "A", "function": "0401", "output": "a.ogg"
    }


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
