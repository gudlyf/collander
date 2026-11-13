from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..db import get_db
from ..models import QueueItem
from ..schemas import QueueItemOut
from ..services import queue
from ..services.importer import prepare_photo
from ..services.settings_store import load_ai_config
from ..services.tags import normalize_tag

router = APIRouter(prefix="/api/queue", tags=["queue"], dependencies=[Depends(require_auth)])

MAX_PHOTOS = 8


def _out(item: QueueItem) -> QueueItemOut:
    return QueueItemOut(
        id=item.id,
        kind=item.kind,
        status=item.status,
        label=item.label,
        file_count=item.file_count,
        recipe_id=item.recipe_id,
        method=item.method,
        warnings=json.loads(item.warnings_json or "[]"),
        error=item.error,
        created_at=item.created_at,
        finished_at=item.finished_at,
    )


def _tags(raw: list[str] | str | None) -> list[str]:
    if isinstance(raw, str):
        raw = raw.split(",")
    return [t for t in (normalize_tag(x) for x in raw or []) if t]


def _enqueue(db: Session, kind: str, label: str, data: dict) -> QueueItem:
    item = QueueItem(kind=kind, label=label[:500], input_json=json.dumps(data))
    db.add(item)
    db.flush()
    return item


@router.get("", response_model=list[QueueItemOut])
def list_queue(db: Session = Depends(get_db), recipe_id: int | None = None, limit: int = 50):
    stmt = select(QueueItem).order_by(QueueItem.id.desc()).limit(limit)
    if recipe_id is not None:
        stmt = stmt.where(QueueItem.recipe_id == recipe_id)
    return [_out(i) for i in db.scalars(stmt)]


class UrlBody(BaseModel):
    url: str = Field(min_length=4)
    use_ai: bool = True
    tags: list[str] = []


@router.post("/url", response_model=QueueItemOut, status_code=202)
def enqueue_url(body: UrlBody, db: Session = Depends(get_db)):
    url = body.url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    item = _enqueue(
        db, "url", url, {"url": url, "use_ai": body.use_ai, "extra_tags": _tags(body.tags)}
    )
    db.commit()
    queue.notify()
    return _out(item)


class TextBody(BaseModel):
    text: str = Field(min_length=1)
    source_url: str | None = None
    tags: list[str] = []


@router.post("/text", response_model=QueueItemOut, status_code=202)
def enqueue_text(body: TextBody, db: Session = Depends(get_db)):
    first = next((ln.strip() for ln in body.text.splitlines() if ln.strip()), "Pasted text")
    item = _enqueue(
        db,
        "text",
        first,
        {"text": body.text, "source_url": body.source_url, "extra_tags": _tags(body.tags)},
    )
    db.commit()
    queue.notify()
    return _out(item)


@router.post("/photo", response_model=QueueItemOut, status_code=202)
async def enqueue_photo(
    files: list[UploadFile] = File(...),
    hint: str = Form(""),
    keep_photo: bool = Form(False),
    tags: str = Form(""),
    db: Session = Depends(get_db),
):
    """Queue one recipe made of 1-8 photos (pages in order). Returns immediately."""
    if not load_ai_config(db).enabled:
        raise HTTPException(409, "Photo import needs an AI provider. Set one up in Settings.")
    if not files or len(files) > MAX_PHOTOS:
        raise HTTPException(422, f"Upload between 1 and {MAX_PHOTOS} photos per recipe.")
    prepared = []
    for f in files:
        p = prepare_photo(await f.read())
        if not p:
            raise HTTPException(422, f"Could not read {f.filename or 'a file'} as an image.")
        prepared.append(p)
    label = hint.strip() or f"Photo import ({len(prepared)} page{'s' if len(prepared) > 1 else ''})"
    item = _enqueue(
        db,
        "photo",
        label,
        {"hint": hint.strip(), "keep_photo": keep_photo, "extra_tags": _tags(tags)},
    )
    item.file_count = len(prepared)
    d = queue.item_dir(item.id)
    d.mkdir(parents=True, exist_ok=True)
    for i, (_mime, data) in enumerate(prepared):
        (d / f"photo-{i:02d}.jpg").write_bytes(data)
    db.commit()
    queue.notify()
    return _out(item)


@router.get("/{item_id}/photos/{n}")
def get_photo(item_id: int, n: int):
    paths = queue.photo_paths(item_id)
    if n < 0 or n >= len(paths):
        raise HTTPException(404)
    return FileResponse(paths[n], media_type="image/jpeg")


@router.post("/{item_id}/retry", response_model=QueueItemOut)
def retry(item_id: int, db: Session = Depends(get_db)):
    item = db.get(QueueItem, item_id)
    if not item:
        raise HTTPException(404)
    if item.status != "failed":
        raise HTTPException(409, "Only failed items can be retried.")
    item.status, item.error, item.finished_at = "queued", None, None
    db.commit()
    queue.notify()
    return _out(item)


@router.delete("/{item_id}", status_code=204)
def remove(item_id: int, db: Session = Depends(get_db)):
    item = db.get(QueueItem, item_id)
    if not item:
        raise HTTPException(404)
    if item.status == "processing":
        raise HTTPException(409, "This item is being processed; try again in a moment.")
    queue.delete_files(item.id)
    db.delete(item)
    db.commit()


@router.post("/clear", status_code=204)
def clear_finished(db: Session = Depends(get_db)):
    """Remove finished items (done + failed) and their stored photos."""
    ids = list(db.scalars(select(QueueItem.id).where(QueueItem.status.in_(("done", "failed")))))
    for i in ids:
        queue.delete_files(i)
    db.execute(delete(QueueItem).where(QueueItem.id.in_(ids)))
    db.commit()
