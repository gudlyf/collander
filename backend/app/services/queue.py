"""Background queue for single-recipe imports (photo, URL, pasted text).

Submitting an import only stores the input and returns. Worker threads pick items
up in order, run the (possibly slow) AI/scraping step, and save the result as a
recipe flagged ``needs_review``. Photos are kept next to the queue item so the
transcription can be checked against the originals.
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
from pathlib import Path

from sqlalchemy import select, update

from ..config import get_settings
from ..db import session_scope
from ..models import QueueItem, utcnow
from . import ai, scraper
from .fetch import FetchError
from .importer import to_data_uri
from .recipes import create_recipe
from .settings_store import load_ai_config
from .tags import all_tag_names

log = logging.getLogger(__name__)

_wake = threading.Event()
_claim_lock = threading.Lock()
_started = False


def item_dir(item_id: int) -> Path:
    return get_settings().queue_dir / str(item_id)


def photo_paths(item_id: int) -> list[Path]:
    d = item_dir(item_id)
    return sorted(d.glob("photo-*.jpg")) if d.exists() else []


def notify() -> None:
    _wake.set()


def _claim() -> int | None:
    with _claim_lock, session_scope() as db:
        item = db.scalar(
            select(QueueItem).where(QueueItem.status == "queued").order_by(QueueItem.id).limit(1)
        )
        if not item:
            return None
        item.status = "processing"
        return item.id


def _process(item_id: int) -> None:
    with session_scope() as db:
        item = db.get(QueueItem, item_id)
        data = json.loads(item.input_json or "{}")
        cfg = load_ai_config(db)
        existing = all_tag_names(db)
        kind = item.kind

    warnings: list[str] = []
    method: str | None = None
    try:
        if kind == "url":
            draft = scraper.draft_from_url(data["url"], cfg, existing, data.get("use_ai", True))
            recipe, method, warnings = draft.recipe, draft.method, draft.warnings
        elif kind == "text":
            draft = scraper.draft_from_text(data["text"], cfg, existing, data.get("source_url"))
            recipe, method, warnings = draft.recipe, draft.method, draft.warnings
        elif kind == "photo":
            photos = [("image/jpeg", p.read_bytes()) for p in photo_paths(item_id)]
            if not photos:
                raise RuntimeError("The uploaded photos are missing.")
            recipe = ai.extract_recipe_from_images(
                cfg, photos, existing_tags=existing, hint=data.get("hint") or None
            )
            if recipe is None:
                raise RuntimeError("No recipe could be read from the photo(s).")
            recipe.source_kind = "photo"
            method = "ai-photo"
            if data.get("keep_photo"):
                recipe.image = to_data_uri(*photos[0])
            if any("[?]" in x.text for x in [*recipe.ingredients, *recipe.steps]):
                warnings.append("Some text was hard to read and is marked with [?].")
        else:
            raise RuntimeError(f"Unknown import kind: {kind}")

        recipe.needs_review = True
        recipe.tags = list(dict.fromkeys([*recipe.tags, *data.get("extra_tags", [])]))
        with session_scope() as db:
            r = create_recipe(db, recipe)
            item = db.get(QueueItem, item_id)
            item.status, item.recipe_id, item.method = "done", r.id, method
            item.label = recipe.title[:500]
            item.warnings_json = json.dumps(warnings)
            item.error = None
            item.finished_at = utcnow()
    except (FetchError, ai.AIError, RuntimeError, KeyError) as e:
        _fail(item_id, str(e))
    except Exception as e:
        log.exception("Queue item %s failed", item_id)
        _fail(item_id, f"Unexpected error: {e}")


def _fail(item_id: int, message: str) -> None:
    with session_scope() as db:
        item = db.get(QueueItem, item_id)
        if item:
            item.status, item.error, item.finished_at = "failed", message, utcnow()


def _worker() -> None:
    while True:
        item_id = _claim()
        if item_id is None:
            _wake.wait(timeout=30)
            _wake.clear()
            continue
        _process(item_id)


def start_workers() -> None:
    global _started
    if _started:
        return
    _started = True
    with session_scope() as db:
        # Anything that was mid-flight when the server stopped goes back in line.
        db.execute(
            update(QueueItem).where(QueueItem.status == "processing").values(status="queued")
        )
    for i in range(max(1, get_settings().queue_workers)):
        threading.Thread(target=_worker, name=f"import-queue-{i}", daemon=True).start()
    notify()


def delete_files(item_id: int) -> None:
    shutil.rmtree(item_dir(item_id), ignore_errors=True)
