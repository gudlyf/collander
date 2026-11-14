from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, selectinload

from ..auth import require_auth
from ..db import get_db
from ..models import Ingredient, Note, Recipe, Step, Tag, recipe_tags
from ..schemas import Bundle, NoteOut, RecipeIn, RecipeList, RecipeOut
from ..services import ai, icons, images, search
from ..services.recipes import (
    create_recipe,
    delete_recipe,
    to_in,
    to_out,
    to_summary,
    update_recipe,
)
from ..services.settings_store import load_ai_config
from ..services.tags import all_tag_names, normalize_tag

router = APIRouter(prefix="/api/recipes", tags=["recipes"], dependencies=[Depends(require_auth)])

_LOAD = (
    selectinload(Recipe.tags),
    selectinload(Recipe.ingredients),
    selectinload(Recipe.steps),
    selectinload(Recipe.notes),
)


def _get(db: Session, recipe_id: int) -> Recipe:
    r = db.scalar(select(Recipe).where(Recipe.id == recipe_id).options(*_LOAD))
    if not r:
        raise HTTPException(404, "Recipe not found")
    return r


def _has_tag(name: str):
    return Recipe.id.in_(
        select(recipe_tags.c.recipe_id)
        .join(Tag, Tag.id == recipe_tags.c.tag_id)
        .where(Tag.name == name)
    )


_MODIFIED = or_(
    Recipe.id.in_(
        select(Ingredient.recipe_id).where(
            or_(Ingredient.override_text.is_not(None), Ingredient.omitted, Ingredient.is_addition)
        )
    ),
    Recipe.id.in_(
        select(Step.recipe_id).where(
            or_(Step.override_text.is_not(None), Step.omitted, Step.is_addition)
        )
    ),
)


@router.get("", response_model=RecipeList)
def list_recipes(
    db: Session = Depends(get_db),
    q: str = "",
    tag: list[str] = Query(default=[]),
    favorite: bool = False,
    modified: bool = False,
    review: bool = False,
    sort: Literal["relevance", "updated", "created", "title", "rating"] = "relevance",
    limit: int = Query(default=60, le=500),
    offset: int = 0,
):
    pq = search.parse_query(q) if q.strip() else search.ParsedQuery()
    conds = []
    for t in [*tag, *pq.tags]:
        conds.append(_has_tag(normalize_tag(t)))
    for t in pq.exclude_tags:
        conds.append(~_has_tag(t))
    if favorite or "favorite" in pq.flags or "fav" in pq.flags:
        conds.append(Recipe.favorite.is_(True))
    if review or "review" in pq.flags:
        conds.append(Recipe.needs_review.is_(True))
    if modified or "modified" in pq.flags:
        conds.append(_MODIFIED)

    scores: dict[int, float] = {}
    try:
        if pq.match:
            hits = search.search_ids(db, pq.match)
            scores = dict(hits)
            ids = list(scores)
            if not ids:
                # Fall back to a plain substring match on titles (e.g. mid-word fragments).
                words = [w for w in q.split() if ":" not in w and not w.startswith("-")]
                if words:
                    like = and_(*[Recipe.title.ilike(f"%{w.strip(chr(34))}%") for w in words])
                    ids = list(db.scalars(select(Recipe.id).where(like)))
            conds.append(Recipe.id.in_(ids))
        if pq.exclude_match:
            conds.append(~Recipe.id.in_(search.matching_ids(db, pq.exclude_match)))
    except OperationalError as e:
        raise HTTPException(400, "Could not understand that search.") from e

    where = and_(*conds) if conds else True
    total = db.scalar(select(func.count()).select_from(Recipe).where(where)) or 0

    stmt = (
        select(Recipe)
        .where(where)
        .options(
            selectinload(Recipe.tags), selectinload(Recipe.ingredients), selectinload(Recipe.steps)
        )
    )
    if sort == "relevance" and scores:
        rows = list(db.scalars(stmt))
        rows.sort(key=lambda r: scores.get(r.id, 0.0))
        rows = rows[offset : offset + limit]
    else:
        order = {
            "relevance": Recipe.updated_at.desc(),
            "updated": Recipe.updated_at.desc(),
            "created": Recipe.created_at.desc(),
            "title": func.lower(Recipe.title).asc(),
            "rating": Recipe.rating.desc().nulls_last(),
        }[sort]
        rows = list(db.scalars(stmt.order_by(order, Recipe.id.desc()).offset(offset).limit(limit)))

    items = []
    for r in rows:
        s = to_summary(r)
        if pq.match and r.id in scores:
            s.snippet = search.snippet(db, r.id, pq.match)
        items.append(s)
    return RecipeList(items=items, total=total)


@router.post("", response_model=RecipeOut, status_code=201)
def create(body: RecipeIn, db: Session = Depends(get_db)):
    r = create_recipe(db, body)
    db.commit()
    icons.maybe_auto_icon(r.id)
    return to_out(_get(db, r.id))


@router.get("/export")
def export_all(db: Session = Depends(get_db), images_: bool = Query(True, alias="images")):
    recipes = db.scalars(select(Recipe).options(*_LOAD).order_by(Recipe.id)).all()
    bundle = Bundle(recipes=[to_in(r, embed_image=images_) for r in recipes])
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    return JSONResponse(
        bundle.model_dump(mode="json"),
        headers={"Content-Disposition": f'attachment; filename="collander-{stamp}.json"'},
    )


@router.get("/{recipe_id}", response_model=RecipeOut)
def get_recipe(recipe_id: int, db: Session = Depends(get_db)):
    return to_out(_get(db, recipe_id))


@router.put("/{recipe_id}", response_model=RecipeOut)
def update(recipe_id: int, body: RecipeIn, db: Session = Depends(get_db)):
    r = _get(db, recipe_id)
    update_recipe(db, r, body)
    db.commit()
    return to_out(_get(db, recipe_id))


class RecipePatch(BaseModel):
    favorite: bool | None = None
    rating: int | None = Field(default=None, ge=0, le=5)
    needs_review: bool | None = None
    tags: list[str] | None = None


@router.patch("/{recipe_id}", response_model=RecipeOut)
def patch(recipe_id: int, body: RecipePatch, db: Session = Depends(get_db)):
    r = _get(db, recipe_id)
    data = body.model_dump(exclude_unset=True)
    if "tags" in data:
        from ..services.tags import get_or_create_tags

        r.tags = get_or_create_tags(db, data.pop("tags") or [])
    for k, v in data.items():
        setattr(r, k, v if not (k == "rating" and v == 0) else None)
    db.flush()
    search.index_recipe(db, r)
    db.commit()
    return to_out(_get(db, recipe_id))


@router.delete("/{recipe_id}", status_code=204)
def delete(recipe_id: int, db: Session = Depends(get_db)):
    delete_recipe(db, _get(db, recipe_id))
    db.commit()


@router.post("/{recipe_id}/image", response_model=RecipeOut)
async def upload_image(recipe_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    r = _get(db, recipe_id)
    name = images.save_image_bytes(await file.read())
    if not name:
        raise HTTPException(422, "That file is not a supported image.")
    images.delete_image(r.image)
    r.image, r.image_generated = name, False
    db.commit()
    return to_out(_get(db, recipe_id))


@router.post("/{recipe_id}/icon", response_model=RecipeOut)
def make_icon(
    recipe_id: int,
    replace_photo: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Make (or remake) this recipe's AI icon. Takes a few seconds to a minute."""
    r = _get(db, recipe_id)
    if r.image and not r.image_generated and not replace_photo:
        raise HTTPException(409, "This recipe has a photo. Remove it first to use an icon.")
    try:
        icons.apply_icon(db, r, replace_photo=replace_photo)
    except ai.AIError as e:
        raise HTTPException(502, str(e)) from e
    db.commit()
    return to_out(_get(db, recipe_id))


# ---- Notes ----------------------------------------------------------------


class NoteBody(BaseModel):
    text: str = Field(min_length=1)


@router.post("/{recipe_id}/notes", response_model=NoteOut, status_code=201)
def add_note(recipe_id: int, body: NoteBody, db: Session = Depends(get_db)):
    r = _get(db, recipe_id)
    note = Note(recipe_id=r.id, text=body.text.strip())
    db.add(note)
    db.flush()
    db.refresh(r)
    search.index_recipe(db, r)
    db.commit()
    return note


@router.put("/{recipe_id}/notes/{note_id}", response_model=NoteOut)
def edit_note(recipe_id: int, note_id: int, body: NoteBody, db: Session = Depends(get_db)):
    note = db.get(Note, note_id)
    if not note or note.recipe_id != recipe_id:
        raise HTTPException(404, "Note not found")
    note.text = body.text.strip()
    db.flush()
    search.index_recipe(db, _get(db, recipe_id))
    db.commit()
    return note


@router.delete("/{recipe_id}/notes/{note_id}", status_code=204)
def delete_note(recipe_id: int, note_id: int, db: Session = Depends(get_db)):
    note = db.get(Note, note_id)
    if not note or note.recipe_id != recipe_id:
        raise HTTPException(404, "Note not found")
    db.delete(note)
    db.flush()
    search.index_recipe(db, _get(db, recipe_id))
    db.commit()


# ---- AI tag suggestions ----------------------------------------------------


@router.post("/suggest-tags", response_model=list[str])
def suggest_tags_for_draft(body: RecipeIn, db: Session = Depends(get_db)):
    cfg = load_ai_config(db)
    try:
        return ai.suggest_tags(cfg, body, all_tag_names(db))
    except ai.AIError as e:
        raise HTTPException(502, str(e)) from e


class AICheckOut(BaseModel):
    recipe: RecipeOut
    issues: list[str]
    changed_lines: bool
    added_tags: list[str]


@router.post("/{recipe_id}/ai-check", response_model=AICheckOut)
def ai_check_recipe(recipe_id: int, db: Session = Depends(get_db)):
    """Tidy formatting and flag problems with the configured AI. Never changes quantities."""
    from ..services.ai_check import check_recipe
    from ..services.importer import apply_check

    cfg = load_ai_config(db)
    r = _get(db, recipe_id)
    try:
        res = check_recipe(cfg, to_in(r), all_tag_names(db))
    except ai.AIError as e:
        raise HTTPException(502, str(e)) from e
    apply_check(db, r, res)
    db.commit()
    return AICheckOut(
        recipe=to_out(_get(db, recipe_id)),
        issues=res.issues,
        changed_lines=res.changed_lines,
        added_tags=res.added_tags,
    )
