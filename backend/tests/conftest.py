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


class FakeAI(list):
    """Records provider calls; set .review to customize the review/tidy response."""

    def __init__(self):
        super().__init__()
        self.review = lambda user: {
            "ingredients": [{"section": "", "text": "2 cups broth"}],
            "steps": [{"section": "", "text": "Heat it."}],
            "issues": [],
            "tags": ["soup"],
        }

    def complete_json(self, system, user, schema, name, images=None):
        self.append({"system": system, "user": user, "name": name, "images": images})
        if name == "tags":
            return {"tags": ["Soup", "vegetarian", "soup"]}
        if name == "review":
            return self.review(user)
        if name == "dish_look":
            return {"look": 'A steaming "Bowl" of golden soup.'}
        if name == "icon":
            return {
                "subject": "a bowl of soup",
                "svg": (
                    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">'
                    '<path d="M120 240h272c0 90-60 150-136 150S120 330 120 240z" fill="#F6F7F4"/>'
                    '<rect x="110" y="220" width="292" height="30" rx="15" fill="#14213D"/>'
                    "</svg>"
                ),
            }
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


@pytest.fixture
def fake_ai(monkeypatch):
    """Replace the provider layer with a canned responder and pretend AI is enabled."""
    from app.services import settings_store
    from app.services.ai import tasks

    fake = FakeAI()
    monkeypatch.setattr(tasks, "get_provider", lambda cfg: fake)
    monkeypatch.setattr("app.services.icons.get_provider", lambda cfg: fake)
    real = settings_store.load_ai_config

    def enabled_cfg(db):
        cfg = real(db)
        cfg.provider = "ollama"
        return cfg

    for mod in (
        "app.services.settings_store",
        "app.services.queue",
        "app.routers.queue",
        "app.routers.imports",
        "app.routers.recipes",
        "app.services.importer",
        "app.services.icons",
        "app.routers.settings",
    ):
        monkeypatch.setattr(f"{mod}.load_ai_config", enabled_cfg, raising=False)
    return fake
