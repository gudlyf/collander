"""Bulk imports (Evernote ENEX, Collander bundles) run as background jobs."""

from __future__ import annotations

import base64
import io
import json
import logging
import threading
import traceback
from pathlib import Path

from PIL import Image, ImageOps
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..db import session_scope
from ..models import ImportJob, Recipe
from ..schemas import Bundle, RecipeIn
from . import ai, enex
from .heuristic import parse_text
from .recipes import create_recipe
from .settings_store import AIConfig, load_ai_config
from .tags import all_tag_names, normalize_tag

log = logging.getLogger(__name__)

# Long edge recommended for vision models; larger images only cost more.
AI_IMAGE_MAX = 1568


def prepare_photo(data: bytes) -> tuple[str, bytes] | None:
    """Normalize an uploaded photo (any format Pillow reads, incl. HEIC) to a JPEG."""
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
        img.thumbnail((AI_IMAGE_MAX, AI_IMAGE_MAX))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=88)
        return "image/jpeg", buf.getvalue()
    except Exception as e:  # noqa: BLE001
        log.info("Could not read photo: %s", e)
        return None


def to_data_uri(mime: str, data: bytes) -> str:
    return f"data:{mime};base64," + base64.b64encode(data).decode()


def _fingerprint(lines) -> list[str]:
    return [" ".join(x.text.lower().split()) for x in lines]


def is_duplicate(db: Session, recipe: RecipeIn) -> bool:
    """True when an existing recipe has the same title, link and ingredients.

    Matching on title alone would drop distinct recipes that happen to share a name
    (two different "Chili" notes), so the ingredient list must match as well.
    """
    q = (
        select(Recipe)
        .where(func.lower(Recipe.title) == recipe.title.strip().lower())
        .options(selectinload(Recipe.ingredients))
    )
    if recipe.source_url:
        q = q.where(Recipe.source_url == recipe.source_url)
    else:
        q = q.where(Recipe.source_url.is_(None))
    want = _fingerprint(recipe.ingredients)
    for existing in db.scalars(q):
        if _fingerprint(existing.ingredients) != want:
            continue
        if want or (existing.original_text or "") == (recipe.original_text or ""):
            return True
    return False


# ---- Evernote --------------------------------------------------------------


def note_to_recipe(
    note: enex.EnexNote, cfg: AIConfig, existing_tags: list[str], use_ai: bool
) -> tuple[RecipeIn, str]:
    """Convert one Evernote note. Returns (recipe, method)."""
    text = note.text
    images = note.images
    recipe: RecipeIn | None = None
    method = "heuristic"

    if use_ai and cfg.enabled:
        if len(text) < 200 and images:
            # Mostly a photo of a recipe card/page: read the image instead.
            prepared = [p for p in (prepare_photo(i.data) for i in images[:4]) if p]
            if prepared:
                recipe = ai.extract_recipe_from_images(
                    cfg, prepared, existing_tags=existing_tags, hint=f"Note title: {note.title}"
                )
                method = "ai-photo"
        else:
            recipe, _ = ai.extract_recipe(
                cfg,
                text,
                existing_tags=existing_tags,
                source_url=note.source_url,
                hint_title=note.title,
            )
            method = "ai"
        if recipe is None:
            method = "heuristic"

    if recipe is None:
        recipe = parse_text(text, title=note.title, source_url=note.source_url)
        if not text.strip():
            recipe.needs_review = True
    else:
        recipe.source_url = note.source_url
        if note.title and note.title.lower() != "untitled":
            recipe.title = note.title[:300]

    recipe.source_kind = "evernote"
    recipe.created_at = note.created
    recipe.tags = list(dict.fromkeys([*map(normalize_tag, note.tags), *recipe.tags]))
    if images:
        recipe.image = to_data_uri(images[0].mime, images[0].data)
    return recipe, method


def preview_enex(path: Path) -> list[dict]:
    out = []
    for note in enex.iter_notes(path, with_resources=False):
        text = note.text
        out.append(
            {
                "index": note.index,
                "title": note.title,
                "tags": note.tags,
                "source_url": note.source_url,
                "snippet": text[:240],
                "image_count": sum(1 for r in note.resources if r.mime.startswith("image/")),
                "likely_recipe": _likely_recipe(note.title, note.tags, text),
            }
        )
    return out


def _likely_recipe(title: str, tags: list[str], text: str) -> bool:
    from .heuristic import looks_like_recipe

    blob = f"{title} {' '.join(tags)}".lower()
    if any(w in blob for w in ("recipe", "recipes", "cooking", "food", "dinner", "dessert")):
        return True
    return looks_like_recipe(text)


# ---- Job runner ------------------------------------------------------------


def _log(job: ImportJob, line: str) -> None:
    job.log = (job.log + line + "\n")[-20000:]


def _run_enex(job_id: int, indexes: set[int], extra_tags: list[str]) -> None:
    with session_scope() as db:
        job = db.get(ImportJob, job_id)
        cfg = load_ai_config(db)
        use_ai = job.use_ai
        path = Path(job.stored_path)
        job.status, job.total, job.processed = "running", len(indexes), 0
        job.imported = job.failed = 0
        db.commit()
        existing = all_tag_names(db)

        for note in enex.iter_notes(path):
            if note.index not in indexes:
                continue
            try:
                recipe, method = note_to_recipe(note, cfg, existing, use_ai)
                recipe.tags = list(dict.fromkeys([*recipe.tags, *extra_tags]))
                if is_duplicate(db, recipe):
                    _log(job, f"skip  (duplicate) {note.title}")
                else:
                    create_recipe(db, recipe)
                    job.imported += 1
                    _log(job, f"ok    [{method}] {note.title}")
                    existing = sorted(set(existing) | set(recipe.tags))
            except Exception as e:  # noqa: BLE001 - keep going on per-note failures
                db.rollback()
                job = db.get(ImportJob, job_id)
                job.failed += 1
                _log(job, f"FAIL  {note.title}: {e}")
                log.warning("ENEX note %s failed: %s", note.index, traceback.format_exc())
            job.processed += 1
            db.commit()
        job.status = "done"


def _run_bundle(job_id: int, skip_duplicates: bool) -> None:
    from .ai_check import check_recipe

    with session_scope() as db:
        job = db.get(ImportJob, job_id)
        job.status = "running"
        db.commit()
        bundle = load_bundle(Path(job.stored_path))
        job.total = len(bundle.recipes)
        cfg = load_ai_config(db)
        use_ai = job.use_ai and cfg.enabled
        existing = all_tag_names(db)
        for recipe in bundle.recipes:
            try:
                if recipe.source_kind == "manual":
                    recipe.source_kind = "bundle"
                if skip_duplicates and is_duplicate(db, recipe):
                    _log(job, f"skip  (duplicate) {recipe.title}")
                else:
                    detail = ""
                    if use_ai:
                        try:
                            res = check_recipe(cfg, recipe, existing)
                            recipe = res.recipe
                            detail = _check_detail(res)
                            existing = sorted(set(existing) | set(recipe.tags))
                        except ai.AIError as e:
                            detail = f" (AI check failed: {e})"
                    create_recipe(db, recipe)
                    job.imported += 1
                    _log(job, f"ok    {recipe.title}{detail}")
            except Exception as e:  # noqa: BLE001
                db.rollback()
                job = db.get(ImportJob, job_id)
                job.failed += 1
                _log(job, f"FAIL  {recipe.title}: {e}")
            job.processed += 1
            db.commit()
        job.status = "done"


def _check_detail(res) -> str:
    bits = []
    if res.changed_lines:
        bits.append("tidied")
    if res.issues:
        bits.append(f"{len(res.issues)} issue(s)")
    if res.added_tags:
        bits.append("tags +" + ",".join(res.added_tags))
    return f" [{'; '.join(bits)}]" if bits else ""


def _run_ai_check(job_id: int, recipe_ids: list[int]) -> None:
    """Re-check existing recipes with the configured AI (background job)."""
    from sqlalchemy.orm import selectinload

    from .ai_check import check_recipe
    from .recipes import to_in

    with session_scope() as db:
        job = db.get(ImportJob, job_id)
        job.status, job.total = "running", len(recipe_ids)
        db.commit()
        cfg = load_ai_config(db)
        existing = all_tag_names(db)
        for rid in recipe_ids:
            r = db.scalar(
                select(Recipe)
                .where(Recipe.id == rid)
                .options(
                    selectinload(Recipe.ingredients),
                    selectinload(Recipe.steps),
                    selectinload(Recipe.notes),
                    selectinload(Recipe.tags),
                )
            )
            if r is None:
                job.processed += 1
                continue
            try:
                res = check_recipe(cfg, to_in(r), existing)
                apply_check(db, r, res)
                job.imported += 1
                _log(job, f"ok    {r.title}{_check_detail(res)}")
            except Exception as e:  # noqa: BLE001
                db.rollback()
                job = db.get(ImportJob, job_id)
                job.failed += 1
                _log(job, f"FAIL  {r.title}: {e}")
            job.processed += 1
            db.commit()
        job.status = "done"


def apply_check(db: Session, r: Recipe, res) -> None:
    """Write a CheckResult back to an existing recipe (notes are synced separately)."""
    from ..models import Note
    from . import search
    from .ai_check import NOTE_PREFIX
    from .recipes import update_recipe

    res.recipe.image = r.image  # the checked copy carries no image; keep the stored one
    update_recipe(db, r, res.recipe)  # replaces lines/tags/flags, keeps notes
    for n in list(r.notes):
        if n.text.startswith(NOTE_PREFIX):
            db.delete(n)
    for n in res.recipe.notes:
        if n.text.startswith(NOTE_PREFIX):
            db.add(Note(recipe_id=r.id, text=n.text))
    db.flush()
    db.refresh(r)
    search.index_recipe(db, r)


def start_ai_check_job(job_id: int, recipe_ids: list[int]) -> None:
    threading.Thread(target=_guard, args=(_run_ai_check, job_id, recipe_ids), daemon=True).start()


def load_bundle(path: Path) -> Bundle:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):  # allow a bare list of recipes
        data = {"recipes": data}
    return Bundle.model_validate(data)


def _guard(fn, job_id: int, *args) -> None:
    try:
        fn(job_id, *args)
    except Exception as e:
        log.exception("Import job %s failed", job_id)
        with session_scope() as db:
            job = db.get(ImportJob, job_id)
            if job:
                job.status = "failed"
                _log(job, f"Job failed: {e}")


def start_enex_job(job_id: int, indexes: list[int], extra_tags: list[str]) -> None:
    tags = [t for t in (normalize_tag(x) for x in extra_tags) if t]
    threading.Thread(
        target=_guard, args=(_run_enex, job_id, set(indexes), tags), daemon=True
    ).start()


def start_bundle_job(job_id: int, skip_duplicates: bool) -> None:
    threading.Thread(
        target=_guard, args=(_run_bundle, job_id, skip_duplicates), daemon=True
    ).start()


def run_bundle_sync(job_id: int, skip_duplicates: bool) -> None:
    _guard(_run_bundle, job_id, skip_duplicates)


def run_enex_sync(job_id: int, indexes: list[int], extra_tags: list[str]) -> None:
    tags = [t for t in (normalize_tag(x) for x in extra_tags) if t]
    _guard(_run_enex, job_id, set(indexes), tags)


def run_ai_check_sync(job_id: int, recipe_ids: list[int]) -> None:
    _guard(_run_ai_check, job_id, recipe_ids)


def mark_interrupted_jobs() -> None:
    with session_scope() as db:
        for job in db.scalars(select(ImportJob).where(ImportJob.status == "running")):
            job.status = "failed"
            _log(
                job,
                "Interrupted by a server restart. Re-run to import the remaining items "
                "(duplicates are skipped).",
            )
