from __future__ import annotations

from dataclasses import dataclass
import json
import urllib.error
import urllib.request

from .catalog import CatalogEntry
from .prompts import (
    review_system_prompt,
    review_user_payload,
    translation_system_prompt,
    translation_user_payload,
)


@dataclass(frozen=True)
class OllamaConfig:
    url: str = "http://127.0.0.1:11434/api/chat"
    model: str = "qwen3.8:27b"
    timeout_seconds: float = 120.0
    retries: int = 3
    think: bool = False


class OllamaBackendError(RuntimeError):
    """A request or response from the local Ollama backend was unusable."""


class OllamaBackend:
    def __init__(self, config: OllamaConfig):
        if config.retries < 0:
            raise ValueError("retries must be non-negative")
        if config.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.config = config

    def _chat(self, system_prompt: str, user_payload: str) -> object:
        request_payload = {
            "model": self.config.model,
            "think": self.config.think,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_payload},
            ],
        }
        request = urllib.request.Request(
            self.config.url,
            data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        last_error: Exception | None = None
        for attempt in range(self.config.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                    body = response.read()
                envelope = json.loads(body.decode("utf-8") if isinstance(body, bytes) else body)
                content = envelope["message"]["content"]
                if not isinstance(content, str):
                    raise ValueError("message.content must be a JSON string")
                return json.loads(content)
            except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as error:
                last_error = error
                if attempt == self.config.retries:
                    raise OllamaBackendError(
                        f"Ollama {self.config.model} request failed after {attempt + 1} attempt(s)"
                    ) from error
        raise OllamaBackendError("Ollama request failed") from last_error

    @staticmethod
    def _records_payload(payload: object, wrapper_key: str) -> list[object]:
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict) and isinstance(payload.get(wrapper_key), list):
            return payload[wrapper_key]
        raise ValueError(f"response must be a JSON array or object containing {wrapper_key}")

    @staticmethod
    def _ordered_translation_records(
        entries: list[CatalogEntry], payload: object
    ) -> list[dict[str, str]]:
        records = OllamaBackend._records_payload(payload, "translations")
        by_key: dict[str, dict[str, str]] = {}
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("translation record must be a JSON object")
            required = ("key", "source_sha256", "zh", "status")
            if any(field not in record for field in required):
                missing = next(field for field in required if field not in record)
                raise ValueError(f"translation record missing {missing}")
            if not all(isinstance(record[field], str) for field in required):
                raise ValueError("translation record fields must be strings")
            key = record["key"]
            if key in by_key:
                raise ValueError("duplicate translation key: " + key)
            by_key[key] = {field: record[field] for field in required}

        ordered: list[dict[str, str]] = []
        expected = {entry.key for entry in entries}
        if set(by_key) != expected:
            raise ValueError("translation response keys do not match request batch")
        for entry in entries:
            record = by_key[entry.key]
            # The catalog, not the model, owns source identity. Models can
            # mistype a copied digest while still returning the right keyed
            # translation; normalize it to the request's authoritative hash.
            ordered.append({**record, "source_sha256": entry.source_sha256})
        return ordered

    @staticmethod
    def _ordered_review_records(
        entries: list[CatalogEntry], payload: object
    ) -> list[dict[str, object]]:
        records = OllamaBackend._records_payload(payload, "reviews")
        by_key: dict[str, dict[str, object]] = {}
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("review record must be a JSON object")
            required = ("key", "source_sha256", "status", "issues", "suggested_zh")
            if any(field not in record for field in required):
                missing = next(field for field in required if field not in record)
                raise ValueError(f"review record missing {missing}")
            if not isinstance(record["key"], str) or not isinstance(record["source_sha256"], str):
                raise ValueError("review key and source_sha256 must be strings")
            if not isinstance(record["status"], str) or not isinstance(record["suggested_zh"], str):
                raise ValueError("review status and suggested_zh must be strings")
            if not isinstance(record["issues"], list) or not all(
                isinstance(issue, str) for issue in record["issues"]
            ):
                raise ValueError("review issues must be a JSON array of strings")
            key = record["key"]
            if key in by_key:
                raise ValueError("duplicate review key: " + key)
            by_key[key] = {
                "key": key,
                "source_sha256": record["source_sha256"],
                "status": record["status"],
                "issues": list(record["issues"]),
                "suggested_zh": record["suggested_zh"],
            }

        expected = {entry.key for entry in entries}
        if set(by_key) != expected:
            raise ValueError("review response keys do not match request batch")
        ordered: list[dict[str, object]] = []
        for entry in entries:
            record = by_key[entry.key]
            ordered.append({**record, "source_sha256": entry.source_sha256})
        return ordered

    def translate_batch(self, entries: list[CatalogEntry]) -> list[dict[str, str]]:
        if not entries:
            return []
        payload = self._chat(translation_system_prompt(), translation_user_payload(entries))
        return self._ordered_translation_records(entries, payload)

    def review_batch(
        self, entries: list[CatalogEntry], translations: list[dict[str, str]]
    ) -> list[dict[str, object]]:
        if len(entries) != len(translations):
            raise ValueError("review entries and translations must have equal lengths")
        if not entries:
            return []
        for entry, translation in zip(entries, translations):
            if translation.get("key") != entry.key:
                raise ValueError("review translation key does not match entry")
            if translation.get("source_sha256") != entry.source_sha256:
                raise ValueError("review translation source hash does not match entry")
            if not isinstance(translation.get("zh"), str):
                raise ValueError("review translation zh must be a string")
        payload = self._chat(review_system_prompt(), review_user_payload(entries, translations))
        return self._ordered_review_records(entries, payload)
