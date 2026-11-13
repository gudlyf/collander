from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..config import get_settings
from ..db import get_db
from ..models import ImportJob, Recipe
from ..schemas import EnexNotePreview, EnexPreview, EnexRunRequest, ImportJobOut
from ..services import importer
from ..services.settings_store import load_ai_config

router = APIRouter(prefix="/api/import", tags=["import"], dependencies=[Depends(require_auth)])


# ---- Background jobs --------------------------------------------------------


async def _store_upload(file: UploadFile, suffix: str) -> Path:
    s = get_settings()
    dest = s.uploads_dir / f"{uuid.uuid4().hex}{suffix}"
    size = 0
    with dest.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > s.max_upload_bytes:
                out.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, "File is too large.")
            out.write(chunk)
    return dest


@router.get("/jobs", response_model=list[ImportJobOut])
def list_jobs(db: Session = Depends(get_db)):
    return db.scalars(select(ImportJob).order_by(ImportJob.id.desc()).limit(20)).all()


@router.get("/jobs/{job_id}", response_model=ImportJobOut)
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(ImportJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.post("/enex", response_model=EnexPreview)
async def upload_enex(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload an Evernote export and list its notes so you can choose what to import."""
    path = await _store_upload(file, ".enex")
    try:
        notes = importer.preview_enex(path)
    except Exception as e:
        path.unlink(missing_ok=True)
        raise HTTPException(422, f"Could not read that ENEX file: {e}") from e
    job = ImportJob(
        kind="evernote",
        status="parsed",
        filename=file.filename or "export.enex",
        stored_path=str(path),
        total=len(notes),
    )
    db.add(job)
    db.commit()
    return EnexPreview(
        job=ImportJobOut.model_validate(job), notes=[EnexNotePreview(**n) for n in notes]
    )


@router.post("/enex/{job_id}/run", response_model=ImportJobOut)
def run_enex(job_id: int, body: EnexRunRequest, db: Session = Depends(get_db)):
    job = db.get(ImportJob, job_id)
    if not job or job.kind != "evernote":
        raise HTTPException(404, "Job not found")
    if job.status == "running":
        raise HTTPException(409, "This import is already running.")
    if not Path(job.stored_path).exists():
        raise HTTPException(410, "The uploaded file is gone; upload it again.")
    if body.use_ai and not load_ai_config(db).enabled:
        raise HTTPException(409, "AI is not configured.")
    job.use_ai = body.use_ai
    job.status = "running"
    db.commit()
    importer.start_enex_job(job.id, body.indexes, body.extra_tags)
    return job


@router.post("/bundle", response_model=ImportJobOut)
async def upload_bundle(
    file: UploadFile = File(...),
    skip_duplicates: bool = Form(True),
    ai_check: bool = Form(False),
    db: Session = Depends(get_db),
):
    """Import a Collander JSON bundle (backup, Google Drive import, etc.)."""
    if ai_check and not load_ai_config(db).enabled:
        raise HTTPException(409, "AI is not configured.")
    path = await _store_upload(file, ".json")
    try:
        bundle = importer.load_bundle(path)
    except Exception as e:
        path.unlink(missing_ok=True)
        raise HTTPException(422, f"Not a valid Collander bundle: {e}") from e
    job = ImportJob(
        kind="bundle",
        status="running",
        filename=file.filename or "bundle.json",
        stored_path=str(path),
        total=len(bundle.recipes),
    )
    db.add(job)
    db.commit()
    importer.start_bundle_job(job.id, skip_duplicates)
    return job


class AICheckRequest(BaseModel):
    scope: Literal["review", "all"] = "review"


@router.post("/ai-check", response_model=ImportJobOut)
def start_ai_check(body: AICheckRequest, db: Session = Depends(get_db)):
    """Tidy and sanity-check existing recipes with the configured AI, in the background."""
    if not load_ai_config(db).enabled:
        raise HTTPException(409, "AI is not configured.")
    if db.scalar(
        select(ImportJob.id).where(ImportJob.kind == "ai-check", ImportJob.status == "running")
    ):
        raise HTTPException(409, "A check is already running.")
    q = select(Recipe.id).order_by(Recipe.id)
    if body.scope == "review":
        q = q.where(Recipe.needs_review.is_(True))
    ids = list(db.scalars(q))
    job = ImportJob(
        kind="ai-check",
        status="running",
        filename=f"{body.scope} recipes",
        stored_path="",
        total=len(ids),
        use_ai=True,
    )
    db.add(job)
    db.commit()
    importer.start_ai_check_job(job.id, ids)
    return job


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(ImportJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status == "running":
        raise HTTPException(409, "Job is running.")
    if job.stored_path:
        Path(job.stored_path).unlink(missing_ok=True)
    db.delete(job)
    db.commit()


def cleanup_uploads() -> None:
    """Remove orphaned upload files (no job references them)."""
    from ..db import session_scope

    with session_scope() as db:
        keep = {Path(p).name for p in db.scalars(select(ImportJob.stored_path))}
    for f in get_settings().uploads_dir.glob("*"):
        if f.name not in keep:
            if f.is_dir():
                shutil.rmtree(f, ignore_errors=True)
            else:
                f.unlink(missing_ok=True)
