from sqlalchemy.orm import Session

from backend.app.ai.providers.rules_fallback import RulesFallbackProvider
from backend.app.ai.services.orchestrator import AIOrchestratorService
from backend.app.models.enums import EffortLevel


class AIService:
    """
    Unified service entry point used by routes and business logic.
    Keeps app code decoupled from provider-specific implementation details.
    """

    def __init__(self, db: Session):
        self.orchestrator = AIOrchestratorService(db)

    def classify_task(self, title: str, description: str = "") -> dict:
        try:
            result = self.orchestrator.classify_task(title=title, description=description)
            return result.model_dump()
        except Exception:
            fallback = self.fallback_classification(title, description)
            if fallback.get("suggested_level"):
                return fallback
            return {
                "suggested_level": EffortLevel.MEDIUM,
                "confidence": 0.55,
                "reason": "AI providers unavailable. Use manual override if needed.",
                "provider_used": "rules",
                "model_used": "rules-default",
                "fallback_used": True,
            }

    def fallback_classification(self, title: str, description: str = "") -> dict:
        try:
            output = RulesFallbackProvider().classify_task(
                title=title,
                description=description,
                model="rules-default",
                timeout_seconds=2,
            )
            return {
                "suggested_level": output.suggested_level,
                "confidence": output.confidence,
                "reason": output.reason,
                "provider_used": "rules",
                "model_used": "rules-default",
                "fallback_used": True,
            }
        except Exception:
            return {
                "suggested_level": EffortLevel.MEDIUM,
                "confidence": 0.55,
                "reason": "Fallback heuristic failed; defaulted to medium effort.",
                "provider_used": "rules",
                "model_used": "rules-default",
                "fallback_used": True,
            }
