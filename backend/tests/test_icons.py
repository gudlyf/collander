import base64
import io

import pytest
from PIL import Image

from app.services.ai import AIError
from app.services.icons import BACKGROUND, render_svg, sanitize_svg

HOSTILE = """<?xml version="1.0"?>
<!DOCTYPE svg [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     viewBox="0 0 100 100" onload="alert(1)">
  <script>alert(1)</script>
  <style>circle { fill: red }</style>
  <image href="/etc/hosts" width="10" height="10"/>
  <foreignObject><div>hi</div></foreignObject>
  <use xlink:href="https://evil.example/x.svg#a"/>
  <text x="10" y="10">&xxe;</text>
  <g transform="translate(10 10)">
    <circle cx="256" cy="256" r="80" fill="url(https://evil.example/p)" onclick="x()"/>
    <rect x="100" y="100" width="50" height="50" fill="#F6F7F4" style="fill:red"/>
  </g>
</svg>"""


def test_sanitize_keeps_shapes_and_drops_everything_else():
    out = sanitize_svg("Here you go:\n" + HOSTILE)
    for bad in (
        "script",
        "style",
        "image",
        "foreignObject",
        "use",
        "text",
        "onload",
        "onclick",
        "url(",
        "evil",
        "passwd",
        "xlink",
    ):
        assert bad not in out, bad
    assert f'fill="{BACKGROUND}"' in out  # the app's tile is always added
    assert 'viewBox="0 0 512 512"' in out
    assert "<circle" in out and 'r="80"' in out  # shape kept, unsafe fill dropped
    assert 'fill="#F6F7F4"' in out and 'transform="translate(10 10)"' in out


@pytest.mark.parametrize(
    "bad", ["", "no svg here", "<svg xmlns='http://www.w3.org/2000/svg'></svg>"]
)
def test_sanitize_rejects_empty_or_missing(bad):
    with pytest.raises(AIError):
        sanitize_svg(bad)


def test_render_makes_a_512_png():
    png = render_svg(sanitize_svg(HOSTILE))
    img = Image.open(io.BytesIO(png))
    assert img.format == "PNG" and img.size == (512, 512)
    assert img.convert("RGB").getpixel((2, 2)) == (0x24, 0x57, 0xB0)


def _png_of(client, name):
    r = client.get(f"/api/images/{name}")
    assert r.status_code == 200
    return Image.open(io.BytesIO(r.content))


def test_icon_endpoint_bulk_job_and_backup(client, fake_ai):
    from app.db import session_scope
    from app.models import ImportJob
    from app.services import icons

    r = client.put("/api/settings/images", json={"provider": "svg", "auto": False})
    assert r.status_code == 200 and r.json()["ready"] is True

    rid = client.post(
        "/api/recipes",
        json={"title": "Icon Soup", "ingredients": [{"text": "2 cups broth"}], "steps": []},
    ).json()["id"]

    # One recipe, on demand.
    r = client.post(f"/api/recipes/{rid}/icon")
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["image_generated"] is True and first["image"].endswith(".png")
    assert _png_of(client, first["image"]).size == (512, 512)
    assert "Icon Soup" in fake_ai[-1]["user"] and "broth" in fake_ai[-1]["user"]

    # Regenerating replaces the old file.
    second = client.post(f"/api/recipes/{rid}/icon").json()
    assert second["image"] != first["image"]
    assert client.get(f"/api/images/{first['image']}").status_code == 404

    # Backups keep the icon and its flag.
    exported = [
        x for x in client.get("/api/recipes/export").json()["recipes"] if x["title"] == "Icon Soup"
    ][0]
    assert exported["image_generated"] is True and exported["image"].startswith("data:image/png")
    restored = client.post("/api/recipes", json={**exported, "title": "Icon Soup copy"}).json()
    assert restored["image_generated"] is True and restored["image"].endswith(".png")

    # A real photo replaces the icon, and the button then refuses to overwrite it.
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 100, 50)).save(buf, "JPEG")
    photo = client.post(f"/api/recipes/{rid}/image", files={"file": ("p.jpg", buf.getvalue())})
    assert photo.json()["image_generated"] is False
    assert client.post(f"/api/recipes/{rid}/icon").status_code == 409

    # Editor saves with a new photo are photos, even if the old image was an icon.
    data_uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    edited = client.put(
        f"/api/recipes/{restored['id']}", json={**restored, "image": data_uri}
    ).json()
    assert edited["image_generated"] is False

    # Bulk: every recipe without an image gets one; photos are untouched.
    bare = client.post("/api/recipes", json={"title": "Plain Toast"}).json()["id"]
    status = client.get("/api/settings/images").json()
    assert status["missing"] >= 1
    with session_scope() as db:
        ids = icons.targets(db, "missing")
        job = ImportJob(
            kind="icons", status="running", filename="t", stored_path="", total=len(ids)
        )
        db.add(job)
        db.flush()
        job_id = job.id
    assert bare in ids and rid not in ids
    icons.run_job_sync(job_id, ids)
    job = client.get(f"/api/import/jobs/{job_id}").json()
    assert job["status"] == "done" and job["failed"] == 0 and job["imported"] == len(ids)
    assert client.get(f"/api/recipes/{bare}").json()["image_generated"] is True
    assert client.get(f"/api/recipes/{rid}").json()["image"] == photo.json()["image"]
    assert client.get("/api/settings/images").json()["missing"] == 0


def test_icons_need_an_engine(client):
    client.put("/api/settings/images", json={"provider": "none"})
    rid = client.post("/api/recipes", json={"title": "No Engine"}).json()["id"]
    assert client.post(f"/api/recipes/{rid}/icon").status_code == 502
    assert client.post("/api/import/icons", json={"scope": "missing"}).status_code == 409


def test_a1111_engine(client, monkeypatch):
    import httpx

    from app.services import icons

    buf = io.BytesIO()
    Image.new("RGB", (768, 768), (0x24, 0x57, 0xB0)).save(buf, "PNG")
    png_b64 = base64.b64encode(buf.getvalue()).decode()
    calls = []

    def fake_get(url, timeout):
        calls.append(("GET", url, None))
        return httpx.Response(200, json=[{"model_name": "z_image_turbo"}])

    def fake_post(url, json, timeout):
        calls.append(("POST", url, json))
        return httpx.Response(200, json={"images": [png_b64]})

    monkeypatch.setattr(icons.httpx, "get", fake_get)
    monkeypatch.setattr(icons.httpx, "post", fake_post)

    r = client.put("/api/settings/images", json={"provider": "a1111", "base_url": ""})
    assert r.json()["ready"] is False
    r = client.put(
        "/api/settings/images",
        json={"provider": "a1111", "base_url": "http://sd.test:7860/", "steps": 8, "cfg_scale": 1},
    )
    assert r.json()["ready"] is True and r.json()["base_url"] == "http://sd.test:7860"
    assert client.post("/api/settings/images/test").json()["models"] == ["z_image_turbo"]

    rid = client.post(
        "/api/recipes", json={"title": "Turbo Tacos", "ingredients": [{"text": "8 tortillas"}]}
    ).json()["id"]
    out = client.post(f"/api/recipes/{rid}/icon").json()
    assert out["image_generated"] is True
    assert _png_of(client, out["image"]).size == (512, 512)
    method, url, body = calls[-1]
    assert (method, url) == ("POST", "http://sd.test:7860/sdapi/v1/txt2img")
    assert body["steps"] == 8 and body["cfg_scale"] == 1.0 and body["width"] == 768
    assert "of turbo tacos, made with tortillas" in body["prompt"] and "textless" in body["prompt"]
    assert "Turbo Tacos" not in body["prompt"] and '"' not in body["prompt"]
    assert "x7" not in body["prompt"] and "768" not in body["prompt"]  # no size tokens

    def down(url, timeout):
        raise httpx.ConnectError("asleep")

    monkeypatch.setattr(icons.httpx, "get", down)
    assert client.post("/api/settings/images/test").status_code == 502
    client.put("/api/settings/images", json={"provider": "none"})


def test_food_subject_drops_quotes_names_and_filler():
    from types import SimpleNamespace as NS

    from app.services.icons import food_subject

    r = NS(
        title='Karen\u2019s Famous "Best" Weeknight Chili!',
        ingredients=[
            NS(text="2 lb ground beef", omitted=False),
            NS(text="1 can (15 oz) kidney beans, drained", omitted=False),
            NS(text="1 cup corn", omitted=True),
        ],
    )
    assert food_subject(r) == "karen's chili, made with ground beef, kidney beans"
    assert food_subject(NS(title="Shepherd's Pie", ingredients=[])) == "shepherd's pie"
    assert food_subject(NS(title="The Best!", ingredients=r.ingredients)) == (
        "a dish made with ground beef, kidney beans"
    )
    assert food_subject(NS(title="The Best", ingredients=[])) == "a home-cooked dish"


def test_stale_save_keeps_a_background_icon(client, fake_ai):
    client.put("/api/settings/images", json={"provider": "svg", "auto": False})
    before = client.post("/api/recipes", json={"title": "Stale Stew"}).json()
    assert before["image"] is None
    with_icon = client.post(f"/api/recipes/{before['id']}/icon").json()

    # The page still holds the pre-icon copy and saves an edit.
    saved = client.put(f"/api/recipes/{before['id']}", json={**before, "description": "x"}).json()
    assert saved["image"] == with_icon["image"] and saved["image_generated"] is True

    # Removing it on purpose (the client knew it was an icon) still works.
    gone = client.put(
        f"/api/recipes/{before['id']}", json={**saved, "image": None, "image_generated": True}
    ).json()
    assert gone["image"] is None and gone["image_generated"] is False
    client.put("/api/settings/images", json={"provider": "none"})


def test_bulk_job_stops_after_repeated_failures(client, monkeypatch):
    from app.db import session_scope
    from app.models import ImportJob
    from app.services import icons

    def broken(*args, **kwargs):
        raise AIError("server asleep")

    monkeypatch.setattr(icons, "make_icon_png", broken)
    client.put("/api/settings/images", json={"provider": "svg"})
    ids = [client.post("/api/recipes", json={"title": f"Fail {i}"}).json()["id"] for i in range(5)]
    with session_scope() as db:
        job = ImportJob(kind="icons", status="running", filename="t", stored_path="", total=5)
        db.add(job)
        db.flush()
        job_id = job.id
    icons.run_job_sync(job_id, ids)
    job = client.get(f"/api/import/jobs/{job_id}").json()
    assert job["status"] == "failed" and job["failed"] == 3 and job["processed"] == 3
    assert "Stopped after 3 failures in a row" in job["log"]
    client.put("/api/settings/images", json={"provider": "none"})


def test_painted_icon_with_text_is_repainted(client, fake_ai, monkeypatch):
    import httpx

    from app.services import icons

    buf = io.BytesIO()
    Image.new("RGB", (768, 768), (0x24, 0x57, 0xB0)).save(buf, "PNG")
    png_b64 = base64.b64encode(buf.getvalue()).decode()
    posts = []
    monkeypatch.setattr(
        icons.httpx,
        "post",
        lambda url, json, timeout: (
            posts.append(json) or httpx.Response(200, json={"images": [png_b64]})
        ),
    )
    verdicts = iter([True, False])  # first painting has text, second is clean
    real = fake_ai.complete_json

    def complete_json(system, user, schema, name, images=None):
        if name == "icon_qa":
            fake_ai.append({"name": name, "images": images})
            return {"has_text": next(verdicts)}
        return real(system, user, schema, name, images)

    monkeypatch.setattr(fake_ai, "complete_json", complete_json)
    client.put("/api/settings/images", json={"provider": "a1111", "base_url": "http://sd.test"})
    rid = client.post("/api/recipes", json={"title": "Wordy Waffles"}).json()["id"]
    assert client.post(f"/api/recipes/{rid}/icon").json()["image_generated"] is True
    assert len(posts) == 2
    qa = [c for c in fake_ai if c["name"] == "icon_qa"]
    assert len(qa) == 2 and qa[0]["images"][0][0] == "image/png"
    client.put("/api/settings/images", json={"provider": "none"})
