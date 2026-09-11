from __future__ import annotations

import json
from unittest import mock
import unittest
from urllib.error import HTTPError

from tools.u6_translation.catalog import CatalogEntry, source_sha256
from tools.u6_translation.ollama_backend import OllamaBackend, OllamaConfig
from tools.u6_translation.prompts import load_glossary, translation_system_prompt


def _entry(key: str, source: str) -> CatalogEntry:
    return CatalogEntry(
        kind="dialogue",
        key=key,
        source=source,
        source_sha256=source_sha256(source),
        context="gameplay",
        origin="fixture",
        protected_tokens=(),
    )


class _Response:
    def __init__(self, body: object) -> None:
        self.body = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def _ollama_response(content: object) -> _Response:
    return _Response({"message": {"role": "assistant", "content": json.dumps(content)}})


class OllamaBackendTest(unittest.TestCase):
    def setUp(self) -> None:
        self.entries = [_entry("dialogue:one", "One"), _entry("dialogue:two", "Two")]

    def test_prompt_glossary_loader_ignores_policy_comments(self) -> None:
        entries = load_glossary()

        self.assertEqual(len(entries), 5)
        self.assertTrue(all(entry.en != "# policy traditional_chinese=warning" for entry in entries))

    def test_prompt_contains_u6_rules_without_u7_guide_names_or_sections(self) -> None:
        prompt = translation_system_prompt()

        self.assertIn("U6 glossary", prompt)
        self.assertIn("繁體中文", prompt)
        self.assertNotIn("Translation_Guide.md", prompt)
        self.assertNotIn("Lord British", prompt)
        self.assertNotIn("八環法術翻譯", prompt)

    def test_prompt_requires_one_translation_without_repeating_the_sentence(self) -> None:
        prompt = translation_system_prompt()

        self.assertIn("exactly one", prompt)
        self.assertIn("Do not repeat", prompt)

    def test_translate_posts_json_only_request_and_returns_batch_order(self) -> None:
        response = _ollama_response(
            [
                {
                    "key": self.entries[1].key,
                    "source_sha256": self.entries[1].source_sha256,
                    "zh": "第二句",
                    "status": "translated",
                },
                {
                    "key": self.entries[0].key,
                    "source_sha256": self.entries[0].source_sha256,
                    "zh": "第一句",
                    "status": "translated",
                },
            ]
        )
        with mock.patch("urllib.request.urlopen", return_value=response) as urlopen:
            result = OllamaBackend(OllamaConfig()).translate_batch(self.entries)

        self.assertEqual([record["key"] for record in result], [entry.key for entry in self.entries])
        self.assertEqual([record["zh"] for record in result], ["第一句", "第二句"])
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["model"], "qwen3.8:27b")
        self.assertFalse(payload["think"])
        self.assertFalse(payload["stream"])
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 120.0)
        self.assertEqual([item["key"] for item in json.loads(payload["messages"][1]["content"])["entries"]], [entry.key for entry in self.entries])
        self.assertIn("繁體中文", payload["messages"][0]["content"])
        self.assertIn("聖者", payload["messages"][0]["content"])
        self.assertNotIn("fixture", payload["messages"][1]["content"])

    def test_translate_replaces_model_hash_with_catalog_hash(self) -> None:
        response = _ollama_response(
            [
                {
                    "key": self.entries[0].key,
                    "source_sha256": "0" * 64,
                    "zh": "第一句",
                    "status": "translated",
                },
                {
                    "key": self.entries[1].key,
                    "source_sha256": self.entries[1].source_sha256,
                    "zh": "第二句",
                    "status": "translated",
                },
            ]
        )
        with mock.patch("urllib.request.urlopen", return_value=response):
            result = OllamaBackend(OllamaConfig()).translate_batch(self.entries)

        self.assertEqual(
            [record["source_sha256"] for record in result],
            [entry.source_sha256 for entry in self.entries],
        )

    def test_review_requires_schema_and_preserves_batch_order(self) -> None:
        translations = [
            {"key": entry.key, "source_sha256": entry.source_sha256, "zh": f"譯文{index}", "status": "translated"}
            for index, entry in enumerate(self.entries)
        ]
        response = _ollama_response(
            {
                "reviews": [
                    {
                        "key": self.entries[1].key,
                        "source_sha256": self.entries[1].source_sha256,
                        "status": "advisory",
                        "issues": ["語氣"],
                        "suggested_zh": "建議二",
                    },
                    {
                        "key": self.entries[0].key,
                        "source_sha256": self.entries[0].source_sha256,
                        "status": "ok",
                        "issues": [],
                        "suggested_zh": "第一句",
                    },
                ]
            }
        )
        with mock.patch("urllib.request.urlopen", return_value=response) as urlopen:
            result = OllamaBackend(OllamaConfig()).review_batch(self.entries, translations)

        self.assertEqual([record["key"] for record in result], [entry.key for entry in self.entries])
        self.assertEqual(result[1]["suggested_zh"], "建議二")
        user_payload = json.loads(json.loads(urlopen.call_args.args[0].data)["messages"][1]["content"])
        self.assertEqual(user_payload["entries"][0]["translation"], "譯文0")

    def test_http_failure_is_retried_and_can_recover(self) -> None:
        error = HTTPError("http://127.0.0.1:11434/api/chat", 503, "busy", {}, None)
        response = _ollama_response(
            [
                {
                    "key": self.entries[0].key,
                    "source_sha256": self.entries[0].source_sha256,
                    "zh": "第一句",
                    "status": "translated",
                },
                {
                    "key": self.entries[1].key,
                    "source_sha256": self.entries[1].source_sha256,
                    "zh": "第二句",
                    "status": "translated",
                },
            ]
        )
        with mock.patch("urllib.request.urlopen", side_effect=[error, response]) as urlopen:
            result = OllamaBackend(OllamaConfig(retries=1)).translate_batch(self.entries)

        self.assertEqual(len(result), 2)
        self.assertEqual(urlopen.call_count, 2)

    def test_malformed_json_is_retried_and_original_error_is_chained(self) -> None:
        malformed = _Response(b"not json")
        with mock.patch("urllib.request.urlopen", return_value=malformed) as urlopen:
            with self.assertRaises(RuntimeError) as raised:
                OllamaBackend(OllamaConfig(retries=2)).translate_batch(self.entries)

        self.assertEqual(urlopen.call_count, 3)
        self.assertIsInstance(raised.exception.__cause__, ValueError)

    def test_missing_message_content_is_retried_and_rejected(self) -> None:
        response = _Response({"message": {"role": "assistant"}})
        with mock.patch("urllib.request.urlopen", return_value=response) as urlopen:
            with self.assertRaises(RuntimeError):
                OllamaBackend(OllamaConfig(retries=1)).translate_batch(self.entries)

        self.assertEqual(urlopen.call_count, 2)

    def test_missing_translation_fields_are_rejected_without_network_fallback(self) -> None:
        response = _ollama_response(
            [{"key": self.entries[0].key, "source_sha256": self.entries[0].source_sha256, "zh": "缺少狀態"}]
        )
        with mock.patch("urllib.request.urlopen", return_value=response) as urlopen:
            with self.assertRaises(ValueError) as raised:
                OllamaBackend(OllamaConfig(retries=0)).translate_batch(self.entries)

        self.assertEqual(urlopen.call_count, 1)
        self.assertIn("status", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
