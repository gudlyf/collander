"""Provider-agnostic AI tasks: recipe extraction and tagging."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ValidationError

from ...schemas import IngredientIn, NoteIn, RecipeIn, StepIn
from ..settings_store import AIConfig
from ..tags import normalize_tag
from .providers import AIError, AIFormatError, ImageInput, get_provider

log = logging.getLogger(__name__)

# Keep prompts well inside every provider's context window (local models included).
MAX_SOURCE_CHARS = 60_000


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }


_STR = {"type": "string"}
_LINE = _obj({"section": _STR, "text": _STR})

RECIPE_SCHEMA = _obj(
    {
        "is_recipe": {"type": "boolean"},
        "title": _STR,
        "description": _STR,
        "servings": _STR,
        "prep_time": _STR,
        "cook_time": _STR,
        "total_time": _STR,
        "ingredients": {"type": "array", "items": _LINE},
        "steps": {"type": "array", "items": _LINE},
        "notes": {"type": "array", "items": _STR},
        "tags": {"type": "array", "items": _STR},
    }
)

TAGS_SCHEMA = _obj({"tags": {"type": "array", "items": _STR}})


class _Line(BaseModel):
    section: str = ""
    text: str


class _Extracted(BaseModel):
    is_recipe: bool
    title: str
    description: str = ""
    servings: str = ""
    prep_time: str = ""
    cook_time: str = ""
    total_time: str = ""
    ingredients: list[_Line] = []
    steps: list[_Line] = []
    notes: list[str] = []
    tags: list[str] = []


TAGGING_GUIDE = """\
Tags help a home cook find recipes later. Choose 3-8 short, lowercase tags covering:
- course (e.g. breakfast, main, side, dessert, snack, drink, sauce, bread)
- main ingredient or protein (e.g. chicken, beef, tofu, salmon, lentils)
- cuisine when clear (e.g. italian, mexican, thai, indian)
- diet only when the recipe truly qualifies (vegetarian, vegan, gluten-free, dairy-free)
- method or occasion when notable (slow-cooker, instant-pot, grilling, holiday, weeknight)
Strongly prefer tags from the existing vocabulary when one fits; only invent a new tag
when nothing existing is appropriate. Use singular forms and hyphens instead of spaces."""

EXTRACT_SYSTEM = f"""\
You convert source material (a web page, a note, or a document) into a structured recipe.

Rules:
- Copy ingredient lines and steps faithfully. Keep the original quantities, units and wording;
  do not convert units, rescale, or "improve" the recipe.
- One ingredient per entry, starting with the quantity when there is one (e.g. "2 cups flour").
- If ingredients or steps are grouped (e.g. "For the sauce"), put the group name in "section";
  otherwise use "".
- Split instructions into individual steps. Remove step numbers like "1." from the text.
- Put tips, variations, storage advice and the author's notes in "notes" (short entries).
- Use "" for any field the source does not provide. Never invent ingredients or steps.
- Ignore page chrome: navigation, ads, comments, newsletter prompts, related recipes.
- Set "is_recipe" to false if the material does not contain a recipe.

{TAGGING_GUIDE}"""

TAG_SYSTEM = f"""You assign tags to recipes.\n\n{TAGGING_GUIDE}"""

PHOTO_SYSTEM = f"""\
You read photos of recipes (recipe cards, cookbook pages, handwritten notes, screenshots)
and transcribe them into a structured recipe.

Rules:
- Transcribe exactly what is written. Keep the original quantities, units and wording;
  do not convert units, rescale, or "improve" the recipe.
- Multiple photos are pages of the same recipe, in order.
- For handwriting you cannot read with confidence, give your best reading followed by "[?]".
- One ingredient per entry, starting with the quantity when there is one.
- If ingredients or steps are grouped (e.g. "For the sauce"), put the group name in "section";
  otherwise use "".
- Split instructions into individual steps. Remove step numbers like "1." from the text.
- Put margin notes, tips and variations in "notes".
- Use "" for any field the photos do not show. Never invent ingredients or steps.
- Set "is_recipe" to false if the photos do not contain a recipe.

{TAGGING_GUIDE}"""


def _call(
    cfg: AIConfig,
    system: str,
    user: str,
    schema: dict,
    name: str,
    model_cls,
    images: list[ImageInput] | None = None,
):
    provider = get_provider(cfg)
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            data = provider.complete_json(system, user, schema, name, images=images)
            return model_cls.model_validate(data)
        except (ValidationError, AIFormatError) as e:
            last_err = e
            log.warning("AI response invalid (attempt %d): %s", attempt + 1, e)
    raise AIError(f"The model's response did not match the expected format: {last_err}")


def _to_recipe(result: _Extracted, *, hint_title: str | None, source_url: str | None) -> RecipeIn:
    return RecipeIn(
        title=(result.title.strip() or hint_title or "Untitled recipe")[:300],
        description=result.description.strip(),
        source_url=source_url,
        servings=_blank(result.servings),
        prep_time=_blank(result.prep_time),
        cook_time=_blank(result.cook_time),
        total_time=_blank(result.total_time),
        ingredients=[
            IngredientIn(text=i.text.strip(), section=_blank(i.section))
            for i in result.ingredients
            if i.text.strip()
        ],
        steps=[
            StepIn(text=s.text.strip(), section=_blank(s.section))
            for s in result.steps
            if s.text.strip()
        ],
        notes=[NoteIn(text=n.strip()) for n in result.notes if n.strip()],
        tags=_clean_tags(result.tags),
    )


def extract_recipe_from_images(
    cfg: AIConfig, images: list[ImageInput], *, existing_tags: list[str], hint: str | None = None
) -> RecipeIn | None:
    user = _vocab_text(existing_tags)
    if hint:
        user += f"\n\nNote from the user about these photos: {hint}"
    user += "\n\nTranscribe the recipe in the attached photo(s)."
    result: _Extracted = _call(
        cfg, PHOTO_SYSTEM, user, RECIPE_SCHEMA, "recipe", _Extracted, images=images
    )
    if not result.is_recipe or not (result.ingredients or result.steps):
        return None
    return _to_recipe(result, hint_title=None, source_url=None)


def _vocab_text(existing_tags: list[str]) -> str:
    if not existing_tags:
        return "Existing tag vocabulary: (none yet)"
    return "Existing tag vocabulary: " + ", ".join(sorted(existing_tags)[:400])


def _blank(s: str) -> str | None:
    s = (s or "").strip()
    return s or None


def extract_recipe(
    cfg: AIConfig,
    source_text: str,
    *,
    existing_tags: list[str],
    source_url: str | None = None,
    hint_title: str | None = None,
) -> tuple[RecipeIn | None, list[str]]:
    """Returns (recipe or None if the source isn't a recipe, warnings)."""
    warnings: list[str] = []
    text = source_text.strip()
    if len(text) > MAX_SOURCE_CHARS:
        warnings.append(
            f"Source was long ({len(text):,} characters); only the first "
            f"{MAX_SOURCE_CHARS:,} were sent to the AI. Check the result against the original."
        )
        text = text[:MAX_SOURCE_CHARS]

    parts = [_vocab_text(existing_tags)]
    if source_url:
        parts.append(f"Source URL: {source_url}")
    if hint_title:
        parts.append(f"Title hint: {hint_title}")
    parts.append("<source>\n" + text + "\n</source>")
    result: _Extracted = _call(
        cfg, EXTRACT_SYSTEM, "\n\n".join(parts), RECIPE_SCHEMA, "recipe", _Extracted
    )
    if not result.is_recipe or not (result.ingredients or result.steps):
        return None, warnings

    return _to_recipe(result, hint_title=hint_title, source_url=source_url), warnings


class _Tags(BaseModel):
    tags: list[str]


def suggest_tags(cfg: AIConfig, recipe: RecipeIn, existing_tags: list[str]) -> list[str]:
    lines = [f"Title: {recipe.title}"]
    if recipe.description:
        lines.append(f"Description: {recipe.description}")
    if recipe.tags:
        lines.append(f"Tags already on the recipe: {', '.join(recipe.tags)}")
    lines.append("Ingredients:\n" + "\n".join(f"- {i.text}" for i in recipe.ingredients))
    lines.append("Steps:\n" + "\n".join(f"- {s.text}" for s in recipe.steps[:30]))
    user = _vocab_text(existing_tags) + "\n\n<recipe>\n" + "\n".join(lines) + "\n</recipe>"
    result: _Tags = _call(cfg, TAG_SYSTEM, user, TAGS_SCHEMA, "tags", _Tags)
    return _clean_tags(result.tags)


def _clean_tags(tags: list[str]) -> list[str]:
    out: list[str] = []
    for t in tags:
        n = normalize_tag(t)
        if n and n not in out:
            out.append(n)
    return out[:10]
