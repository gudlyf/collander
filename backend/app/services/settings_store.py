"""Key/value settings stored in the database, with environment overrides."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import AppSetting

PROVIDERS = ("none", "anthropic", "openai", "google", "ollama")

# Sensible defaults per provider. Model names change often: override them on the
# Settings page or with COLLANDER_AI_MODEL rather than editing code.
DEFAULT_MODELS = {
    "anthropic": "claude-opus-5-5",
    "openai": "gpt-5-mini",
    "google": "gemini-2.5-flash",
    "ollama": "llama3.1",
}


def get_value(db: Session, key: str, default: str | None = None) -> str | None:
    row = db.get(AppSetting, key)
    return row.value if row else default


def set_value(db: Session, key: str, value: str | None) -> None:
    row = db.get(AppSetting, key)
    if value is None:
        if row:
            db.delete(row)
        return
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))


@dataclass
class AIConfig:
    provider: str
    model: str | None
    anthropic_api_key: str | None
    openai_api_key: str | None
    openai_base_url: str | None
    google_api_key: str | None
    ollama_base_url: str
    auto_tag: bool

    @property
    def effective_model(self) -> str | None:
        if self.provider == "none":
            return None
        return self.model or DEFAULT_MODELS.get(self.provider)

    @property
    def enabled(self) -> bool:
        if self.provider == "anthropic":
            return bool(self.anthropic_api_key)
        if self.provider == "openai":
            # Custom base URLs (e.g. LM Studio, vLLM) may not need a key.
            return bool(self.openai_api_key or self.openai_base_url)
        if self.provider == "google":
            return bool(self.google_api_key)
        return self.provider == "ollama"


def key_source(db: Session, name: str) -> str:
    env_val = getattr(get_settings(), name)
    if env_val:
        return "env"
    return "db" if get_value(db, name) else ""


def load_ai_config(db: Session) -> AIConfig:
    s = get_settings()

    def pick(name: str) -> str | None:
        # Environment wins for secrets so they never need to be in the database.
        return getattr(s, name) or get_value(db, name)

    provider = get_value(db, "ai_provider") or s.ai_provider or "none"
    if provider not in PROVIDERS:
        provider = "none"
    return AIConfig(
        provider=provider,
        model=get_value(db, "ai_model") or s.ai_model,
        anthropic_api_key=pick("anthropic_api_key"),
        openai_api_key=pick("openai_api_key"),
        openai_base_url=get_value(db, "openai_base_url") or s.openai_base_url,
        google_api_key=pick("google_api_key"),
        ollama_base_url=get_value(db, "ollama_base_url") or s.ollama_base_url,
        auto_tag=(get_value(db, "auto_tag", "true") == "true"),
    )
