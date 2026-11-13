import time

from conftest import FIXTURES

RECIPE = {
    "title": "Tomato Soup",
    "description": "Cozy",
    "tags": ["Soup", "Vegetarian"],
    "ingredients": [
        {
            "text": "2 cups skim milk",
            "override_text": "2 cups almond milk",
            "override_note": "dairy-free",
        },
        {"text": "1 1/2 lb tomatoes"},
        {"text": "basil", "is_addition": True},
    ],
    "steps": [{"text": "Simmer the tomatoes for 20 minutes."}],
    "notes": [{"text": "Great with grilled cheese"}],
}


def test_requires_auth(client):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as anon:
        assert anon.get("/api/recipes").status_code == 401
        assert anon.post("/api/auth/login", json={"password": "nope"}).status_code == 401


def test_crud_overrides_notes_and_search(client):
    r = client.post("/api/recipes", json=RECIPE)
    assert r.status_code == 201, r.text
    rec = r.json()
    rid = rec["id"]
    milk = rec["ingredients"][0]
    assert milk["text"] == "2 cups skim milk" and milk["override_text"] == "2 cups almond milk"
    assert rec["tags"] == ["soup", "vegetarian"]

    # Search finds the original *and* the override text, plus tags and notes.
    for q in ["tomatoes", "almond", "skim", "tag:soup", '"grilled cheese"', "is:modified"]:
        res = client.get("/api/recipes", params={"q": q}).json()
        assert rid in [i["id"] for i in res["items"]], q
    assert client.get("/api/recipes", params={"q": "soup -tomato"}).json()["total"] == 0

    # Notes endpoints
    n = client.post(f"/api/recipes/{rid}/notes", json={"text": "Add a pinch of sugar"}).json()
    client.put(f"/api/recipes/{rid}/notes/{n['id']}", json={"text": "Add a pinch of brown sugar"})
    got = client.get(f"/api/recipes/{rid}").json()
    assert [x["text"] for x in got["notes"]][0] == "Add a pinch of brown sugar"
    assert client.get("/api/recipes", params={"q": "brown sugar"}).json()["total"] >= 1

    # Updating via the editor keeps notes.
    upd = dict(RECIPE, title="Tomato Soup II", notes=[])
    got = client.put(f"/api/recipes/{rid}", json=upd).json()
    assert got["title"] == "Tomato Soup II" and len(got["notes"]) == 2

    # Patch favorite + tags, tag rename/merge.
    client.patch(f"/api/recipes/{rid}", json={"favorite": True, "tags": ["soup", "lunch"]})
    assert client.get("/api/recipes", params={"favorite": True}).json()["total"] >= 1
    tags = {t["name"]: t["id"] for t in client.get("/api/tags").json()}
    client.put(f"/api/tags/{tags['lunch']}", json={"name": "soup"})
    assert client.get(f"/api/recipes/{rid}").json()["tags"] == ["soup"]

    # Export -> re-import bundle (skip duplicates)
    bundle = client.get("/api/recipes/export").json()
    assert bundle["format"] == "collander-bundle" and bundle["recipes"]
    client.delete(f"/api/recipes/{rid}")
    assert client.get(f"/api/recipes/{rid}").status_code == 404


def _wait_job(client, job_id):
    for _ in range(100):
        job = client.get(f"/api/import/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.1)
    raise AssertionError("job did not finish")


def test_enex_import_without_ai(client):
    with open(FIXTURES / "sample.enex", "rb") as f:
        r = client.post("/api/import/enex", files={"file": ("sample.enex", f, "application/xml")})
    assert r.status_code == 200, r.text
    preview = r.json()
    likely = {n["title"]: n["likely_recipe"] for n in preview["notes"]}
    assert likely["Grandma's Chili"] is True
    assert likely["Car insurance renewal"] is False
    job_id = preview["job"]["id"]
    r = client.post(
        f"/api/import/enex/{job_id}/run", json={"indexes": [0], "extra_tags": ["evernote"]}
    )
    assert r.status_code == 200, r.text
    job = _wait_job(client, job_id)
    assert job["imported"] == 1, job["log"]
    res = client.get("/api/recipes", params={"q": "chili"}).json()["items"]
    chili = client.get(f"/api/recipes/{res[0]['id']}").json()
    assert chili["source_kind"] == "evernote"
    assert set(chili["tags"]) >= {"dinner", "family-recipes", "evernote"}
    assert [i["text"] for i in chili["ingredients"]][0] == "1 lb ground beef"
    assert chili["image"]
    assert chili["created_at"].startswith("2019-03-05")

    # Running it again skips the duplicate.
    client.post(f"/api/import/enex/{job_id}/run", json={"indexes": [0]})
    assert _wait_job(client, job_id)["imported"] == 0


def test_queue_text_and_photo_with_fake_ai(client, fake_ai):
    r = client.post("/api/queue/text", json={"text": "some soup recipe", "tags": ["test"]})
    assert r.status_code == 202
    item_id = r.json()["id"]
    with open(FIXTURES / "sample.enex", "rb"):
        pass
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (60, 40), "white").save(buf, "JPEG")
    r = client.post(
        "/api/queue/photo",
        files=[("files", ("a.jpg", buf.getvalue(), "image/jpeg"))],
        data={"keep_photo": "true"},
    )
    assert r.status_code == 202, r.text
    photo_id = r.json()["id"]

    for _ in range(100):
        items = {i["id"]: i for i in client.get("/api/queue").json()}
        if all(items[i]["status"] in ("done", "failed") for i in (item_id, photo_id)):
            break
        time.sleep(0.1)
    for i in (item_id, photo_id):
        assert items[i]["status"] == "done", items[i]
        rec = client.get(f"/api/recipes/{items[i]['recipe_id']}").json()
        assert rec["needs_review"] is True
        assert "soup" in rec["tags"]
    photo_rec = client.get(f"/api/recipes/{items[photo_id]['recipe_id']}").json()
    assert photo_rec["image"] and photo_rec["source_kind"] == "photo"
    assert any(c["images"] for c in fake_ai)
    assert client.get(f"/api/queue/{photo_id}/photos/0").status_code == 200


def test_duplicate_detection_needs_matching_ingredients(client):
    import json

    from app.db import session_scope
    from app.schemas import RecipeIn
    from app.services.importer import is_duplicate

    a = {"title": "Chili", "ingredients": [{"text": "1 lb beef"}]}
    b = {"title": "Chili", "ingredients": [{"text": "2 cans black beans"}]}
    payload = json.dumps({"recipes": [a, b, a]})
    r = client.post(
        "/api/import/bundle",
        files={"file": ("b.json", payload, "application/json")},
        data={"skip_duplicates": "true"},
    )
    job = _wait_job(client, r.json()["id"])
    assert job["imported"] == 2, job["log"]  # the third is an exact repeat of the first
    with session_scope() as db:
        assert is_duplicate(db, RecipeIn(**a))
        assert not is_duplicate(db, RecipeIn(title="Chili", ingredients=[{"text": "tofu"}]))


def test_reimport_with_ai_check_skips_everything(client, fake_ai):
    """AI tidying changes the stored lines; re-runs must still recognise the source."""
    import json

    fake_ai.review = lambda user: {
        "ingredients": [{"section": "", "text": "3 eggs, beaten"}],
        "steps": [{"section": "", "text": "Whisk."}],
        "issues": [],
        "tags": [],
    }
    payload = json.dumps(
        {
            "recipes": [
                {
                    "title": "Rerun Omelette",
                    "ingredients": [{"text": "▢ 3 eggs, beaten"}],
                    "steps": [{"text": "1. Whisk."}],
                }
            ]
        }
    )
    for expected in (1, 0):
        r = client.post(
            "/api/import/bundle",
            files={"file": ("b.json", payload, "application/json")},
            data={"skip_duplicates": "true", "ai_check": "true"},
        )
        job = _wait_job(client, r.json()["id"])
        assert job["imported"] == expected, job["log"]
    got = client.get("/api/recipes", params={"q": "Rerun Omelette"}).json()["items"]
    rec = client.get(f"/api/recipes/{got[0]['id']}").json()
    assert rec["ingredients"][0]["text"] == "3 eggs, beaten"  # tidied, yet still deduped


def test_enex_rerun_with_ai_skips_before_calling_ai(client, fake_ai):
    with open(FIXTURES / "sample.enex", "rb") as f:
        preview = client.post(
            "/api/import/enex", files={"file": ("s.enex", f, "application/xml")}
        ).json()
    job_id = preview["job"]["id"]
    # Note 1 is new (photo-only); run it twice with AI on.
    client.post(f"/api/import/enex/{job_id}/run", json={"indexes": [1], "use_ai": True})
    first = _wait_job(client, job_id)
    calls_after_first = len(fake_ai)
    client.post(f"/api/import/enex/{job_id}/run", json={"indexes": [1], "use_ai": True})
    second = _wait_job(client, job_id)
    assert first["imported"] == 1, first["log"]
    assert second["imported"] == 0, second["log"]
    assert len(fake_ai) == calls_after_first  # no AI calls for the duplicate


def test_health_reports_version_and_commit(client, monkeypatch):
    from app import __version__, commit

    commit.cache_clear()
    monkeypatch.setenv("COLLANDER_COMMIT", "0123456789abcdef0123456789abcdef01234567")
    try:
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json() == {
            "status": "ok",
            "version": __version__,
            "commit": "0123456789abcdef0123456789abcdef01234567",
        }
    finally:
        commit.cache_clear()
