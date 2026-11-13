import os
import tempfile
from pathlib import Path

import pytest

# Point the app at a throwaway data dir *before* app modules are imported.
_TMP = tempfile.mkdtemp(prefix="collander-test-")
os.environ["COLLANDER_DATA_DIR"] = _TMP
os.environ.pop("COLLANDER_PASSWORD", None)
os.environ["COLLANDER_AI_PROVIDER"] = "none"

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        r = c.post("/api/auth/setup", json={"password": "correct horse"})
        assert r.status_code == 204, r.text
        yield c


@pytest.fixture
def fake_ai(monkeypatch):
    """Replace the provider layer with a canned responder."""
    from app.services import settings_store
    from app.services.ai import tasks

    calls = []

    class Fake:
        def complete_json(self, system, user, schema, name, images=None):
            calls.append({"system": system, "user": user, "name": name, "images": images})
            if name == "tags":
                return {"tags": ["Soup", "vegetarian", "soup"]}
            return {
                "is_recipe": True,
                "title": "Fake Soup",
                "description": "",
                "servings": "4",
                "prep_time": "",
                "cook_time": "",
                "total_time": "",
                "ingredients": [{"section": "", "text": "2 cups broth"}],
                "steps": [{"section": "", "text": "Heat it."}],
                "notes": ["Freezes well."],
                "tags": ["Soup", "Weeknight Dinner"],
            }

    monkeypatch.setattr(tasks, "get_provider", lambda cfg: Fake())
    real = settings_store.load_ai_config

    def enabled_cfg(db):
        cfg = real(db)
        cfg.provider = "ollama"
        return cfg

    for mod in (
        "app.services.settings_store",
        "app.services.queue",
        "app.routers.queue",
        "app.services.importer",
    ):
        monkeypatch.setattr(f"{mod}.load_ai_config", enabled_cfg, raising=False)
    return calls
