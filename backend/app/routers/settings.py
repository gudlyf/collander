from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..db import get_db
from ..schemas import AISettingsIn, AISettingsOut
from ..services import ai
from ..services.settings_store import (
    DEFAULT_MODELS,
    PROVIDERS,
    key_source,
    load_ai_config,
    set_value,
)

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_auth)])

_KEYS = {
    "anthropic": "anthropic_api_key",
    "openai": "openai_api_key",
    "google": "google_api_key",
}


def _out(db: Session) -> AISettingsOut:
    cfg = load_ai_config(db)
    return AISettingsOut(
        provider=cfg.provider,
        model=cfg.model,
        ollama_base_url=cfg.ollama_base_url,
        openai_base_url=cfg.openai_base_url,
        effective_model=cfg.effective_model,
        keys={p: key_source(db, k) for p, k in _KEYS.items()},
        auto_tag=cfg.auto_tag,
    )


@router.get("/ai", response_model=AISettingsOut)
def get_ai(db: Session = Depends(get_db)):
    return _out(db)


@router.get("/ai/defaults")
def ai_defaults():
    return {"providers": list(PROVIDERS), "default_models": DEFAULT_MODELS}


@router.put("/ai", response_model=AISettingsOut)
def put_ai(body: AISettingsIn, db: Session = Depends(get_db)):
    data = body.model_dump(exclude_unset=True)
    if "provider" in data:
        if data["provider"] not in PROVIDERS:
            raise HTTPException(422, "Unknown provider")
        set_value(db, "ai_provider", data["provider"])
    if "model" in data:
        set_value(db, "ai_model", (data["model"] or "").strip() or None)
    for k in ("ollama_base_url", "openai_base_url"):
        if k in data:
            set_value(db, k, (data[k] or "").strip() or None)
    if "auto_tag" in data and data["auto_tag"] is not None:
        set_value(db, "auto_tag", "true" if data["auto_tag"] else "false")
    for k in _KEYS.values():
        if k in data and data[k] is not None:
            set_value(db, k, data[k].strip() or None)
    db.commit()
    return _out(db)


@router.post("/ai/test")
def test_ai(db: Session = Depends(get_db)):
    """Send a tiny request to the configured provider to check that it works."""
    cfg = load_ai_config(db)
    try:
        provider = ai.get_provider(cfg)
        result = provider.complete_json(
            "Reply with JSON only.",
            'Return {"ok": true}.',
            {
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
                "additionalProperties": False,
            },
            "ping",
        )
    except ai.AIError as e:
        raise HTTPException(502, str(e)) from e
    return {"ok": bool(result.get("ok")), "provider": cfg.provider, "model": cfg.effective_model}
