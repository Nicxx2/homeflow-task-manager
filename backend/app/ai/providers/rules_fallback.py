from backend.app.ai.providers.base import BaseAIProvider
from backend.app.ai.schemas.classification import AIModelInfo, ProviderTaskClassificationOutput
from backend.app.models.enums import EffortLevel


class RulesFallbackProvider(BaseAIProvider):
    provider_name = "rules"

    def classify_task(self, *, title: str, description: str, model: str, timeout_seconds: int) -> ProviderTaskClassificationOutput:
        _ = (model, timeout_seconds)
        text = f"{title} {description}".lower().strip()
        tokens = text.split()
        token_count = len(tokens)

        high_keywords = {
            "heavy",
            "deep clean",
            "whole",
            "entire",
            "everything",
            "all day",
            "storage room",
            "garage",
            "move furniture",
            "unpack",
            "sort everything",
            "organize everything",
            "migration",
            "complex",
            "integration",
            "audit",
            "refactor",
            "incident",
        }
        medium_keywords = {
            "prepare",
            "review",
            "plan",
            "organize",
            "meeting",
            "follow-up",
            "follow",
            "document",
            "thoroughly",
            "clean bedroom",
            "multiple",
            "several",
        }

        quantity_numbers = [int(item) for item in tokens if item.isdigit()]
        max_quantity = max(quantity_numbers) if quantity_numbers else 0

        high_signal_count = 0
        if token_count >= 36:
            high_signal_count += 1
        if max_quantity >= 20:
            high_signal_count += 2
        if max_quantity >= 10:
            high_signal_count += 1
        if any(word in text for word in high_keywords):
            high_signal_count += 2
        if any(word in text for word in {"boxes", "box", "rooms", "room", "furniture", "heavy", "everything"}):
            high_signal_count += 1
        if any(word in text for word in {"many", "multiple", "whole", "entire", "all"}):
            high_signal_count += 1

        if high_signal_count >= 3:
            return ProviderTaskClassificationOutput(
                suggested_level=EffortLevel.HIGH,
                confidence=0.79 if max_quantity >= 20 or "heavy" in text else 0.73,
                reason="Rules fallback detected large quantity, physical effort, or whole-scope workload.",
            )

        medium_signal_count = 0
        if token_count >= 14:
            medium_signal_count += 1
        if max_quantity >= 5:
            medium_signal_count += 1
        if any(word in text for word in medium_keywords):
            medium_signal_count += 1

        if medium_signal_count >= 2:
            return ProviderTaskClassificationOutput(
                suggested_level=EffortLevel.MEDIUM,
                confidence=0.66,
                reason="Rules fallback detected moderate multi-step or moderately scaled effort.",
            )

        return ProviderTaskClassificationOutput(
            suggested_level=EffortLevel.LOW,
            confidence=0.58,
            reason="Rules fallback detected a small and straightforward task.",
        )

    def list_models(self, *, timeout_seconds: int) -> list[AIModelInfo]:
        _ = timeout_seconds
        return [
            AIModelInfo(
                display_name="Rules Heuristic (Local)",
                provider_name=self.provider_name,
                model_identifier="rules-default",
                available=True,
                enabled=True,
                health_status="healthy",
                notes="Deterministic local fallback.",
            )
        ]

    def health_check(self, *, model: str, timeout_seconds: int) -> dict:
        _ = (model, timeout_seconds)
        return {"ok": True, "status": "healthy", "message": "Rules provider is always available."}
