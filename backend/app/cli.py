"""Command-line helpers, e.g. inside the container:

docker compose exec collander python -m app.cli import-bundle /data/recipes.json
docker compose exec collander python -m app.cli import-enex /data/export.enex --ai --tag evernote
docker compose exec collander python -m app.cli export /data/backup.json
docker compose exec collander python -m app.cli reindex
docker compose exec collander python -m app.cli set-password
"""

from __future__ import annotations

import argparse
import getpass
import json
import shutil
import sys
import uuid
from pathlib import Path

from .config import get_settings
from .db import session_scope
from .migrate import upgrade_db


def _new_job(kind: str, src: Path) -> int:
    from .models import ImportJob

    dest = get_settings().uploads_dir / f"{uuid.uuid4().hex}{src.suffix}"
    shutil.copyfile(src, dest)
    with session_scope() as db:
        job = ImportJob(kind=kind, status="running", filename=src.name, stored_path=str(dest))
        db.add(job)
        db.flush()
        return job.id


def _report(job_id: int) -> None:
    from .models import ImportJob

    with session_scope() as db:
        job = db.get(ImportJob, job_id)
        print(job.log)
        print(
            f"{job.status}: {job.imported} imported, {job.failed} failed, {job.processed} processed"
        )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="collander")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("import-bundle", help="Import a Collander JSON bundle")
    b.add_argument("path", type=Path)
    b.add_argument("--allow-duplicates", action="store_true")
    b.add_argument("--ai-check", action="store_true", help="Tidy/sanity-check each recipe with AI")

    c = sub.add_parser("ai-check", help="Tidy/sanity-check existing recipes with AI")
    c.add_argument("--all", action="store_true", help="All recipes (default: needs-review only)")

    e = sub.add_parser("import-enex", help="Import an Evernote .enex export")
    e.add_argument("path", type=Path)
    e.add_argument("--ai", action="store_true", help="Structure notes with the configured AI")
    e.add_argument("--all", action="store_true", help="Import every note, not just likely recipes")
    e.add_argument("--tag", action="append", default=[], help="Extra tag (repeatable)")

    x = sub.add_parser("export", help="Write all recipes to a JSON bundle")
    x.add_argument("path", type=Path)
    x.add_argument("--no-images", action="store_true")

    sub.add_parser("reindex", help="Rebuild the search index")
    sub.add_parser("set-password", help="Set the login password")

    args = p.parse_args(argv)
    upgrade_db()

    if args.cmd == "import-bundle":
        from .services import importer

        job_id = _new_job("bundle", args.path)
        with session_scope() as db:
            from .models import ImportJob

            db.get(ImportJob, job_id).use_ai = args.ai_check
        importer.run_bundle_sync(job_id, skip_duplicates=not args.allow_duplicates)
        _report(job_id)
    elif args.cmd == "import-enex":
        from .services import importer

        notes = importer.preview_enex(args.path)
        indexes = [n["index"] for n in notes if args.all or n["likely_recipe"]]
        print(f"{len(notes)} notes, importing {len(indexes)}")
        job_id = _new_job("evernote", args.path)
        with session_scope() as db:
            from .models import ImportJob

            db.get(ImportJob, job_id).use_ai = args.ai
        importer.run_enex_sync(job_id, indexes, args.tag)
        _report(job_id)
    elif args.cmd == "export":
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from .models import Recipe
        from .schemas import Bundle
        from .services.recipes import to_in

        with session_scope() as db:
            rows = db.scalars(
                select(Recipe).options(
                    selectinload(Recipe.tags),
                    selectinload(Recipe.ingredients),
                    selectinload(Recipe.steps),
                    selectinload(Recipe.notes),
                )
            ).all()
            bundle = Bundle(recipes=[to_in(r, embed_image=not args.no_images) for r in rows])
        args.path.write_text(json.dumps(bundle.model_dump(mode="json"), indent=1))
        print(f"Wrote {len(bundle.recipes)} recipes to {args.path}")
    elif args.cmd == "ai-check":
        from sqlalchemy import select

        from .models import ImportJob, Recipe
        from .services import importer

        with session_scope() as db:
            q = select(Recipe.id).order_by(Recipe.id)
            if not args.all:
                q = q.where(Recipe.needs_review.is_(True))
            ids = list(db.scalars(q))
            job = ImportJob(kind="ai-check", status="running", filename="cli", stored_path="")
            db.add(job)
            db.flush()
            job_id = job.id
        print(f"Checking {len(ids)} recipes")
        importer.run_ai_check_sync(job_id, ids)
        _report(job_id)
    elif args.cmd == "reindex":
        from .services import search

        with session_scope() as db:
            print(f"Indexed {search.rebuild(db)} recipes")
    elif args.cmd == "set-password":
        from . import auth

        pw = getpass.getpass("New password: ")
        if len(pw) < 8 or pw != getpass.getpass("Again: "):
            print("Passwords must match and be at least 8 characters.", file=sys.stderr)
            return 1
        with session_scope() as db:
            auth.set_password(db, pw)
        print("Password updated; existing sessions were signed out.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
