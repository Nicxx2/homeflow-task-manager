from collections.abc import Callable

import httpx

from backend.app.ai.prompts.task_effort_prompt import build_task_effort_prompt
from backend.app.ai.providers.base import BaseAIProvider
from backend.app.ai.schemas.classification import AIModelInfo, ProviderTaskClassificationOutput
from backend.app.ai.utils.json_parsing import safe_parse_json_object


class OllamaProvider(BaseAIProvider):
    provider_name = "ollama"

    def __init__(self, *, base_url: str, client_factory: Callable[..., httpx.Client] | None = None):
        self.base_url = base_url.rstrip("/")
        self._client_factory = client_factory or httpx.Client

    def classify_task(self, *, title: str, description: str, model: str, timeout_seconds: int) -> ProviderTaskClassificationOutput:
        prompt = build_task_effort_prompt(title, description)
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.1,
                "top_p": 0.9,
                "num_predict": 220,
            },
        }

        raw_text = self._post_generate(payload=payload, timeout_seconds=timeout_seconds, min_read_seconds=20)
        try:
            parsed = safe_parse_json_object(raw_text)
            return ProviderTaskClassificationOutput.model_validate(parsed)
        except Exception:
            retry_payload = dict(payload)
            retry_payload["prompt"] = (
                prompt
                + "\nReturn JSON only. Do not include any text before or after the JSON object."
            )
            raw_retry = self._post_generate(payload=retry_payload, timeout_seconds=timeout_seconds, min_read_seconds=20)
            parsed_retry = safe_parse_json_object(raw_retry)
            return ProviderTaskClassificationOutput.model_validate(parsed_retry)

    def _timeout(self, *, timeout_seconds: int, min_read_seconds: int) -> httpx.Timeout:
        read_timeout = float(max(timeout_seconds, min_read_seconds))
        return httpx.Timeout(connect=5.0, read=read_timeout, write=30.0, pool=5.0)

    def _post_generate(self, *, payload: dict, timeout_seconds: int, min_read_seconds: int) -> str:
        with self._client_factory(timeout=self._timeout(timeout_seconds=timeout_seconds, min_read_seconds=min_read_seconds)) as client:
            response = client.post(f"{self.base_url}/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()
            text = data.get("response", "")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("Ollama returned an empty response.")
            return text

    def list_models(self, *, timeout_seconds: int) -> list[AIModelInfo]:
        with self._client_factory(timeout=self._timeout(timeout_seconds=timeout_seconds, min_read_seconds=10)) as client:
            response = client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            payload = response.json()
            models = payload.get("models", [])
            if not isinstance(models, list):
                return []

            items: list[AIModelInfo] = []
            for item in models:
                model_name = item.get("name")
                if not isinstance(model_name, str):
                    continue
                items.append(
                    AIModelInfo(
                        display_name=model_name,
                        provider_name=self.provider_name,
                        model_identifier=model_name,
                        available=True,
                        enabled=True,
                        health_status="healthy",
                        notes="Detected from Ollama tags endpoint.",
                    )
                )
            return items

    def health_check(self, *, model: str, timeout_seconds: int) -> dict:
        with self._client_factory(timeout=self._timeout(timeout_seconds=timeout_seconds, min_read_seconds=20)) as client:
            response = client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": 'Return {"ok":true} as JSON only.',
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.0, "num_predict": 16},
                },
            )
            response.raise_for_status()
            return {"ok": True, "status": "healthy", "message": f"Model '{model}' responded."}
