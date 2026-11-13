# Contributing to Collander

Thanks for helping. Bug reports, fixes and small focused features are all welcome.

## Before you start

- For anything bigger than a bug fix, open an issue first to talk through the idea.
- Keep the app easy to self-host: one container, SQLite, no required external services. AI must stay optional for everything except photo import.
- Never commit personal data: databases, `.env` files, Evernote exports, or real recipe collections. `.gitignore` covers the usual paths (`data/`, `local-imports/`, `*.enex`).

## Setup

```bash
# Backend
cd backend
uv sync
COLLANDER_DATA_DIR=./data uv run uvicorn app.main:app --reload   # http://localhost:8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev                                                      # http://localhost:5173
```

The Vite dev server proxies `/api` to the backend.

## Checks

Run these before opening a pull request; CI runs the same ones.

```bash
cd backend
uv run ruff format --check app tests
uv run ruff check app tests
uv run pytest

cd ../frontend
npx tsc -b
npm test
npm run build

cd ..
docker compose build
```

Tests never call a real AI provider. Use the `fake_ai` fixture in `backend/tests/conftest.py` for AI paths.

## Project layout

```
backend/app/
  main.py              FastAPI app, static file serving
  models.py            SQLAlchemy models
  schemas.py           Pydantic models; RecipeIn is the shared import format
  routers/             HTTP endpoints
  services/
    ai/                provider backends (providers.py) and tasks (extraction, tagging)
    queue.py           background queue for photo/link/text imports
    importer.py        Evernote + bundle jobs
    enex.py            streaming .enex parser
    scraper.py         URL -> recipe (schema.org first, then AI)
    search.py          FTS5 index and query parser
  migrations/          Alembic migrations
frontend/src/
  pages/               screens
  components/          shared pieces (ingredient/step lists, tag input, icons)
  scale.ts             quantity parsing and scaling
```

## Database changes

Change `backend/app/models.py`, then create a migration:

```bash
cd backend
COLLANDER_DATA_DIR=./data uv run alembic upgrade head
COLLANDER_DATA_DIR=./data uv run alembic revision --autogenerate -m "describe the change"
```

Review the generated file. The FTS5 search table is managed by hand, so autogenerate ignores it. Migrations run automatically when the app starts.

## Adding an AI provider

Implement `complete_json(system, user, schema, name, images=None) -> dict` in `backend/app/services/ai/providers.py`, register it in `get_provider`, and add it to `PROVIDERS` and `DEFAULT_MODELS` in `services/settings_store.py` and to the Settings page.

## Style

- Python: ruff (format and lint), type hints, short docstrings where intent isn't obvious.
- TypeScript: strict mode; plain CSS in `styles.css` using the color tokens on `:root`.
- UI copy: plain, sentence case, and say what a button does ("Save recipe", not "Submit").

## Pull requests

- Keep PRs focused; describe what changed and how you tested it.
- Add or update tests for behavior changes.
- Screenshots help for UI changes.

By contributing, you agree that your contributions are licensed under the MIT License.
