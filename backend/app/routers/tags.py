from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..db import get_db
from ..models import Recipe, Tag, recipe_tags
from ..schemas import TagOut, TagRename
from ..services import search
from ..services.tags import normalize_tag

router = APIRouter(prefix="/api/tags", tags=["tags"], dependencies=[Depends(require_auth)])


@router.get("", response_model=list[TagOut])
def list_tags(db: Session = Depends(get_db)):
    rows = db.execute(
        select(Tag.id, Tag.name, func.count(recipe_tags.c.recipe_id))
        .outerjoin(recipe_tags, recipe_tags.c.tag_id == Tag.id)
        .group_by(Tag.id)
        .order_by(Tag.name)
    ).all()
    return [TagOut(id=i, name=n, count=c) for i, n, c in rows]


def _reindex(db: Session, recipes: list[Recipe]) -> None:
    db.flush()
    for r in recipes:
        search.index_recipe(db, r)


@router.put("/{tag_id}", response_model=TagOut)
def rename_tag(tag_id: int, body: TagRename, db: Session = Depends(get_db)):
    """Rename a tag. Renaming onto an existing tag merges the two."""
    tag = db.get(Tag, tag_id)
    if not tag:
        raise HTTPException(404, "Tag not found")
    new = normalize_tag(body.name)
    if not new:
        raise HTTPException(422, "Invalid tag name")
    affected = list(tag.recipes)
    target = db.scalar(select(Tag).where(Tag.name == new))
    if target and target.id != tag.id:
        for r in affected:
            if target not in r.tags:
                r.tags.append(target)
            r.tags.remove(tag)
        db.delete(tag)
        tag = target
    else:
        tag.name = new
    _reindex(db, affected)
    db.commit()
    return TagOut(id=tag.id, name=tag.name, count=len(tag.recipes))


@router.delete("/{tag_id}", status_code=204)
def delete_tag(tag_id: int, db: Session = Depends(get_db)):
    tag = db.get(Tag, tag_id)
    if not tag:
        raise HTTPException(404, "Tag not found")
    affected = list(tag.recipes)
    db.delete(tag)
    db.flush()
    for r in affected:
        db.refresh(r)
    _reindex(db, affected)
    db.commit()
