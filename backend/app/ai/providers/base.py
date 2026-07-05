from abc import ABC, abstractmethod

from backend.app.ai.schemas.classification import AIModelInfo, ProviderTaskClassificationOutput


class BaseAIProvider(ABC):
    provider_name: str

    @abstractmethod
    def classify_task(self, *, title: str, description: str, model: str, timeout_seconds: int) -> ProviderTaskClassificationOutput:
        raise NotImplementedError()

    @abstractmethod
    def list_models(self, *, timeout_seconds: int) -> list[AIModelInfo]:
        raise NotImplementedError()

    @abstractmethod
    def health_check(self, *, model: str, timeout_seconds: int) -> dict:
        raise NotImplementedError()

    def generate_json(self, *, prompt: str, model: str, timeout_seconds: int, max_tokens: int = 220) -> dict:
        _ = (prompt, model, timeout_seconds, max_tokens)
        raise NotImplementedError("Provider does not support general JSON generation.")
