from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..db import get_db
from ..models import Recipe
from ..schemas import AISettingsIn, AISettingsOut, ImageSettingsIn, ImageSettingsOut
from ..services import ai, icons
from ..services.settings_store import (
    DEFAULT_IMAGE_MODELS,
    DEFAULT_MODELS,
    IMAGE_PROVIDERS,
    PROVIDERS,
    key_source,
    load_ai_config,
    load_image_config,
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


# ---- Recipe icons -------------------------------------------------------------


def _images_out(db: Session) -> ImageSettingsOut:
    cfg = load_image_config(db)
    problem = icons.check_ready(load_ai_config(db), cfg)
    count = lambda cond: db.scalar(select(func.count()).select_from(Recipe).where(cond))  # noqa: E731
    return ImageSettingsOut(
        provider=cfg.provider,
        model=cfg.model,
        effective_model=cfg.effective_model,
        auto=cfg.auto,
        base_url=cfg.base_url,
        steps=cfg.steps,
        cfg_scale=cfg.cfg_scale,
        ready=problem is None,
        problem=problem if cfg.provider != "none" else None,
        missing=count(Recipe.image.is_(None)),
        generated=count(Recipe.image_generated.is_(True)),
    )


@router.get("/images", response_model=ImageSettingsOut)
def get_images(db: Session = Depends(get_db)):
    return _images_out(db)


@router.get("/images/defaults")
def images_defaults():
    return {"providers": list(IMAGE_PROVIDERS), "default_models": DEFAULT_IMAGE_MODELS}


@router.put("/images", response_model=ImageSettingsOut)
def put_images(body: ImageSettingsIn, db: Session = Depends(get_db)):
    data = body.model_dump(exclude_unset=True)
    if "provider" in data:
        if data["provider"] not in IMAGE_PROVIDERS:
            raise HTTPException(422, "Unknown icon engine")
        set_value(db, "image_provider", data["provider"])
    if "model" in data:
        set_value(db, "image_model", (data["model"] or "").strip() or None)
    if "auto" in data and data["auto"] is not None:
        set_value(db, "auto_icons", "true" if data["auto"] else "false")
    if "base_url" in data:
        set_value(db, "image_base_url", (data["base_url"] or "").strip().rstrip("/") or None)
    for key in ("steps", "cfg_scale"):
        if data.get(key) is not None:
            set_value(db, f"image_{key}", str(data[key]))
    db.commit()
    return _images_out(db)


@router.post("/images/test")
def test_images(db: Session = Depends(get_db)):
    """Check that the image server answers (A1111-compatible engines only; others cost money)."""
    cfg = load_image_config(db)
    if cfg.provider != "a1111":
        raise HTTPException(
            400, "Only the Stable Diffusion server can be tested without making an image."
        )
    try:
        models = icons.a1111_models(cfg)
    except ai.AIError as e:
        raise HTTPException(502, str(e)) from e
    return {"ok": True, "models": models}
