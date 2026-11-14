"""Recipe persistence: create/update from ``RecipeIn`` and serialize to API models."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Ingredient, Note, Recipe, Step
from ..schemas import IngredientIn, NoteIn, RecipeIn, RecipeOut, RecipeSummary, StepIn
from . import images, search
from .tags import get_or_create_tags


def has_modifications(r: Recipe) -> bool:
    return any(x.override_text or x.omitted or x.is_addition for x in [*r.ingredients, *r.steps])


def to_summary(r: Recipe) -> RecipeSummary:
    return RecipeSummary(
        id=r.id,
        title=r.title,
        description=r.description,
        image=r.image,
        image_generated=r.image_generated,
        favorite=r.favorite,
        rating=r.rating,
        needs_review=r.needs_review,
        total_time=r.total_time,
        tags=sorted(t.name for t in r.tags),
        has_modifications=has_modifications(r),
        updated_at=r.updated_at,
    )


def to_out(r: Recipe) -> RecipeOut:
    return RecipeOut.model_validate(
        {
            **{c: getattr(r, c) for c in RecipeOut.model_fields if c not in ("tags",)},
            "tags": sorted(t.name for t in r.tags),
        }
    )


def to_in(r: Recipe, *, embed_image: bool = False) -> RecipeIn:
    """Serialize for export bundles."""
    return RecipeIn(
        title=r.title,
        description=r.description,
        source_url=r.source_url,
        source_name=r.source_name,
        source_kind=r.source_kind,
        servings=r.servings,
        prep_time=r.prep_time,
        cook_time=r.cook_time,
        total_time=r.total_time,
        rating=r.rating,
        favorite=r.favorite,
        needs_review=r.needs_review,
        original_text=r.original_text,
        tags=sorted(t.name for t in r.tags),
        ingredients=[IngredientIn.model_validate(i, from_attributes=True) for i in r.ingredients],
        steps=[StepIn.model_validate(s, from_attributes=True) for s in r.steps],
        notes=[NoteIn(text=n.text, created_at=n.created_at) for n in r.notes],
        image=images.image_as_data_uri(r.image) if embed_image else None,
        image_generated=bool(r.image_generated and embed_image),
        created_at=r.created_at,
    )


def _apply(db: Session, r: Recipe, data: RecipeIn, *, replace_notes: bool, new: bool) -> None:
    for field in (
        "title",
        "description",
        "source_url",
        "source_name",
        "source_kind",
        "servings",
        "prep_time",
        "cook_time",
        "total_time",
        "rating",
        "favorite",
        "needs_review",
        "original_text",
    ):
        setattr(r, field, getattr(data, field))

    # Image: keep, replace or remove. A changed image is a photo, except an AI icon
    # restored from a backup (a flagged data URI on a new recipe). Edits never set the flag.
    if not new and data.image is None and r.image_generated and not data.image_generated:
        # A page loaded before a background icon arrived saves "no image"; keep the icon.
        # (A client that saw the icon sends image_generated=true when removing it.)
        data = data.model_copy(update={"image": r.image})
    if data.image != r.image:
        generated = new and data.image_generated and (data.image or "").startswith("data:")
        new_name = images.resolve_image(data.image, png=generated)
        if new_name != r.image:
            images.delete_image(r.image)
            r.image = new_name
            r.image_generated = bool(new_name) and generated

    r.ingredients = [
        Ingredient(position=i, **ing.model_dump()) for i, ing in enumerate(data.ingredients)
    ]
    r.steps = [Step(position=i, **st.model_dump()) for i, st in enumerate(data.steps)]
    r.tags = get_or_create_tags(db, data.tags)
    if replace_notes:
        r.notes = [
            Note(text=n.text, **({"created_at": n.created_at} if n.created_at else {}))
            for n in data.notes
        ]


def create_recipe(db: Session, data: RecipeIn) -> Recipe:
    r = Recipe(title=data.title, import_key=data.import_key)
    if data.created_at:
        r.created_at = data.created_at
    db.add(r)
    _apply(db, r, data, replace_notes=True, new=True)
    db.flush()
    search.index_recipe(db, r)
    return r


def update_recipe(db: Session, r: Recipe, data: RecipeIn) -> Recipe:
    # Notes are managed through their own endpoints, so the editor doesn't clobber them.
    _apply(db, r, data, replace_notes=False, new=False)
    db.flush()
    search.index_recipe(db, r)
    return r


def delete_recipe(db: Session, r: Recipe) -> None:
    images.delete_image(r.image)
    search.remove_recipe(db, r.id)
    db.delete(r)
