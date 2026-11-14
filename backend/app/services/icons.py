"""AI-made recipe icons for recipes that have no photo.

Three engines, chosen in Settings:

- ``svg``: the configured chat model draws a small flat SVG. It is sanitized against an
  allowlist, given the app's cobalt tile, and rasterized to PNG; the SVG itself is never
  stored or served.
- ``a1111``: a local Stable Diffusion server with the AUTOMATIC1111 API (A1111, Forge,
  stable-diffusion.cpp's sd-server) paints it.
- ``openai`` / ``google``: an image-generation model paints the icon from a style prompt.

Every engine produces a 512px PNG, stored like any other recipe image with
``image_generated`` set, so a real photo always takes precedence.
"""

from __future__ import annotations

import base64
import io
import logging
import random
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import httpx
from lxml import etree
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..db import session_scope
from ..models import ImportJob, Recipe
from . import images
from .ai.providers import AIError, get_provider
from .settings_store import (
    AIConfig,
    ImageConfig,
    load_ai_config,
    load_image_config,
)

log = logging.getLogger(__name__)

SIZE = 512
BACKGROUND = "#2457B0"
PALETTE = {
    "background (added for you)": BACKGROUND,
    "off-white": "#F6F7F4",
    "navy": "#14213D",
    "light blue": "#9CC0FF",
}
FOOD_COLOURS = "tomato red #D9483B, herb green #3C8D4F, golden yellow #E8A93B, crust brown #8A5A3C"

APP_ICON_EXAMPLE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <path d="M206 92c0 0-16 22-16 34a16 16 0 0 0 32 0c0-12-16-34-16-34z" fill="#9CC0FF"/>
  <rect x="186" y="384" width="140" height="34" rx="12" fill="#14213D"/>
  <path d="M92 212h328c0 112-70 184-164 184S92 324 92 212z" fill="#F6F7F4"/>
  <rect x="34" y="190" width="92" height="40" rx="20" fill="none"
        stroke="#14213D" stroke-width="18"/>
  <rect x="386" y="190" width="92" height="40" rx="20" fill="none"
        stroke="#14213D" stroke-width="18"/>
  <rect x="74" y="186" width="364" height="48" rx="24" fill="#14213D"/>
  <g fill="#2457B0"><circle cx="160" cy="270" r="14"/><circle cx="208" cy="270" r="14"/></g>
</svg>"""

SVG_SYSTEM = f"""You draw small, flat icons for a recipe app. Each icon shows the dish as one
simple, recognizable subject, in the same style as the app's own icon (a colander), shown here:

{APP_ICON_EXAMPLE}

Rules:
- Canvas is viewBox="0 0 512 512". A full cobalt ({BACKGROUND}) background is added for you;
  do not draw a background.
- Keep the subject centered and inside x 96-416, y 96-416. Prefer 6-30 shapes.
- Flat geometric shapes with rounded ends and corners. Bold silhouettes; thick navy strokes
  only where they help. No gradients, shadows, textures, text, letters or numbers.
- Colours: off-white #F6F7F4, navy #14213D, light blue #9CC0FF, plus at most three food
  colours such as {FOOD_COLOURS}. Avoid cobalt for the subject itself.
- Allowed elements: svg, g, rect, circle, ellipse, path, polygon, polyline, line.
  No style, defs, use, image, text, filters, masks or external references.

Return JSON with "subject" (a few words naming what you drew) and "svg" (the complete
<svg> element)."""

SVG_SCHEMA = {
    "type": "object",
    "properties": {"subject": {"type": "string"}, "svg": {"type": "string"}},
    "required": ["subject", "svg"],
    "additionalProperties": False,
}


def raster_prompt(subject: str) -> str:
    return (
        f"A simple flat vector app icon representing {subject}. "
        f"Square tile completely filled with solid cobalt blue {BACKGROUND}, edge to edge, "
        "no border and no rounded corners. One centered subject drawn with a few bold, flat "
        "geometric shapes with rounded corners, taking up about the middle 60% of the tile. "
        "Palette: off-white #F6F7F4, deep navy #14213D, light blue #9CC0FF, plus at most "
        f"three natural food colours such as {FOOD_COLOURS}. Minimal, friendly, modern "
        "flat-design kitchen illustration. No gradients, no shadows, no texture, no text, "
        "no letters, no title or caption, no photorealism, no plate clutter or background scenery."
    )


# ---- Recipe description ---------------------------------------------------

_QTY = re.compile(
    r"^[\d\s½¼¾⅓⅔⅛/.,\-–()]*(cups?|tbsps?|tablespoons?|tsps?|teaspoons?|oz|ounces?|lbs?|"
    r"pounds?|g|grams?|kg|ml|l|liters?|litres?|cans?|cloves?|pinch|dash|large|medium|small|"
    r"whole|packages?|sticks?|slices?|bunch(es)?)?\.?\s+",
    re.I,
)


def _ingredient_name(text: str) -> str:
    name = _QTY.sub("", text.strip()).split(",")[0]
    return re.sub(r"\s*\(.*?\)", "", name).strip()[:40]


# Words that say nothing about how a dish looks.
_FILLER = re.compile(
    r"\b(the|a|an|best|easy|easiest|classic|quick|simple|weeknight|perfect|ultimate|"
    r"homemade|famous|favorite|favourite|copycat|recipe|my|our)\b",
    re.I,
)


def food_subject(r: Recipe) -> str:
    """Describe the dish in plain lowercase words for image models.

    Never quote the title: quoted or capitalized titles get painted in as text. A few
    ingredients give the picture its colours; more than three and the model tends to draw
    the ingredients instead of the dish.
    """
    name = r.title.replace("\u2019", "'").lower()
    name = _FILLER.sub(" ", name)
    name = re.sub(r"[^\w\s'-]", " ", name)
    name = " ".join(name.split()).strip("'- ")
    names = [_ingredient_name(i.text).lower() for i in r.ingredients if not i.omitted]
    names = [n for n in names if n][:3]
    if not name:
        return f"a dish made with {', '.join(names)}" if names else "a home-cooked dish"
    return f"{name}, made with {', '.join(names)}" if names else name


def describe(r: Recipe) -> str:
    """A short, plain description of the dish for the image prompt."""
    names = [_ingredient_name(i.text) for i in r.ingredients if not i.omitted][:8]
    parts = [f"Dish: {r.title.strip()}"]
    if r.description:
        parts.append(f"About: {r.description.strip()[:200]}")
    if names:
        parts.append("Main ingredients: " + ", ".join(n for n in names if n))
    tags = sorted(t.name for t in r.tags)[:8]
    if tags:
        parts.append("Tags: " + ", ".join(tags))
    return "\n".join(parts)


# ---- SVG sanitizing and rendering -------------------------------------------

_SVG_NS = "http://www.w3.org/2000/svg"
_ELEMENTS = {"svg", "g", "rect", "circle", "ellipse", "path", "polygon", "polyline", "line"}
_ATTRS = {
    "x", "y", "width", "height", "rx", "ry", "cx", "cy", "r", "d", "points",
    "x1", "y1", "x2", "y2", "fill", "stroke", "stroke-width", "stroke-linecap",
    "stroke-linejoin", "opacity", "fill-opacity", "stroke-opacity", "fill-rule",
    "transform",
}  # fmt: skip
_SAFE_VALUE = re.compile(r"^[\w\s.,#%()+\-]*$")
_MAX_SVG_CHARS = 100_000
_MAX_ELEMENTS = 1500


def sanitize_svg(markup: str) -> str:
    """Rebuild the model's SVG from allowlisted shapes only, on the app's cobalt tile.

    Anything else (scripts, styles, links, images, text, references) is dropped.
    """
    markup = (markup or "").strip()
    if len(markup) > _MAX_SVG_CHARS:
        raise AIError("The drawn icon was too large.")
    m = re.search(r"<svg\b.*</svg>", markup, re.S | re.I)
    if not m:
        raise AIError("The model did not return an SVG drawing.")
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=False,
        remove_comments=True,
        remove_pis=True,
        recover=True,
    )
    try:
        src = etree.fromstring(m.group(0).encode(), parser)
    except etree.XMLSyntaxError as e:
        raise AIError(f"The drawn icon was not valid SVG: {e}") from e
    if src is None or etree.QName(src).localname != "svg":
        raise AIError("The model did not return an SVG drawing.")

    out = etree.Element(
        f"{{{_SVG_NS}}}svg",
        nsmap={None: _SVG_NS},
        viewBox=f"0 0 {SIZE} {SIZE}",
        width=str(SIZE),
        height=str(SIZE),
    )
    etree.SubElement(out, f"{{{_SVG_NS}}}rect", width=str(SIZE), height=str(SIZE), fill=BACKGROUND)
    count = 0

    def copy(src_el, dst_parent):
        nonlocal count
        for child in src_el:
            if not isinstance(child.tag, str):
                continue
            name = etree.QName(child).localname
            if name not in _ELEMENTS or name == "svg":
                continue
            count += 1
            if count > _MAX_ELEMENTS:
                raise AIError("The drawn icon had too many shapes.")
            el = etree.SubElement(dst_parent, f"{{{_SVG_NS}}}{name}")
            for k, v in child.attrib.items():
                key = etree.QName(k).localname if k.startswith("{") else k
                if k.startswith("{") or key not in _ATTRS:
                    continue
                v = v.strip()
                if len(v) > 20_000 or not _SAFE_VALUE.match(v) or "url" in v.lower():
                    continue
                el.set(key, v)
            if name == "g":
                copy(child, el)

    copy(src, out)
    if count == 0:
        raise AIError("The drawn icon was empty.")
    return etree.tostring(out, encoding="unicode")


def render_svg(svg: str) -> bytes:
    import resvg_py

    try:
        return bytes(
            resvg_py.svg_to_bytes(svg_string=svg, width=SIZE, height=SIZE, skip_system_fonts=True)
        )
    except Exception as e:  # noqa: BLE001 - renderer errors are opaque
        raise AIError(f"Could not render the drawn icon: {e}") from e


# ---- Engines -----------------------------------------------------------------


def _draw_svg(ai_cfg: AIConfig, img_cfg: ImageConfig, description: str) -> bytes:
    if not ai_cfg.enabled:
        raise AIError("Icons drawn as SVG use the AI model; set one up under AI model first.")
    cfg = replace(ai_cfg, model=img_cfg.model) if img_cfg.model else ai_cfg
    provider = get_provider(cfg)
    last: AIError | None = None
    for _ in range(2):  # one retry: drawings occasionally come back malformed
        try:
            res = provider.complete_json(SVG_SYSTEM, description, SVG_SCHEMA, "icon")
            return render_svg(sanitize_svg(str(res.get("svg", ""))))
        except AIError as e:
            last = e
    raise last or AIError("The model could not draw an icon.")


def _paint_openai(ai_cfg: AIConfig, model: str, prompt: str) -> bytes:
    import openai

    client = openai.OpenAI(
        api_key=ai_cfg.openai_api_key or "not-needed",
        base_url=ai_cfg.openai_base_url or None,
        timeout=300,
        max_retries=2,
    )
    kwargs: dict = {"model": model, "prompt": prompt, "n": 1, "size": "1024x1024"}
    if model.startswith("dall-e"):
        kwargs["response_format"] = "b64_json"
    else:
        kwargs["quality"] = "medium"
    try:
        resp = client.images.generate(**kwargs)
    except openai.AuthenticationError as e:
        raise AIError("OpenAI rejected the API key.") from e
    except openai.NotFoundError as e:
        raise AIError(f"OpenAI image model not found: {model}") from e
    except openai.APIStatusError as e:
        raise AIError(f"OpenAI image error ({e.status_code}): {e.message}") from e
    except openai.APIConnectionError as e:
        raise AIError("Could not reach the OpenAI API.") from e
    data = resp.data[0].b64_json if resp.data else None
    if not data:
        raise AIError("OpenAI returned no image.")
    return base64.b64decode(data)


def _paint_google(ai_cfg: AIConfig, model: str, prompt: str) -> bytes:
    from google import genai
    from google.genai import errors, types

    client = genai.Client(api_key=ai_cfg.google_api_key)
    try:
        if model.startswith("imagen"):
            resp = client.models.generate_images(
                model=model,
                prompt=prompt,
                config=types.GenerateImagesConfig(number_of_images=1, aspect_ratio="1:1"),
            )
            imgs = resp.generated_images or []
            if imgs and imgs[0].image and imgs[0].image.image_bytes:
                return imgs[0].image.image_bytes
        else:
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                    image_config=types.ImageConfig(aspect_ratio="1:1"),
                ),
            )
            for cand in resp.candidates or []:
                for part in (cand.content.parts if cand.content else None) or []:
                    if part.inline_data and part.inline_data.data:
                        return part.inline_data.data
    except errors.APIError as e:
        raise AIError(f"Google image error ({e.code}): {e.message}") from e
    raise AIError("Google returned no image (it may have been blocked by a safety filter).")


# Turbo models run at CFG 1.0, where the negative prompt has no effect, so the positive
# prompt itself has to rule out text. Avoid ground/floor/horizon words (they paint a bar
# along the bottom) and size tokens like "512x512" (they get painted as text).
A1111_NEGATIVE = (
    "text, letters, words, typography, watermark, signature, logo, ui, faces, photorealistic, "
    "blur, jpeg artifacts"
)
A1111_SIZE = 768


def a1111_prompt(subject: str) -> str:
    return (
        f"Flat minimalist vector illustration of {subject}, centered, drawn with a few bold "
        "simple geometric shapes with rounded corners, filling about the middle half of the "
        f"picture. One uniform solid cobalt blue {BACKGROUND.lower()} field fills the entire "
        "background edge to edge. Colors: off-white #f6f7f4, deep navy #14213d, light blue "
        "#9cc0ff, and natural food colors. Clean modern flat design, no shading, no gradients, "
        "no texture. Completely textless image without any title, caption, words, letters, "
        "numbers or labels."
    )


def _a1111_url(img_cfg: ImageConfig) -> str:
    if not img_cfg.base_url:
        raise AIError("Set the Stable Diffusion server address first.")
    return img_cfg.base_url.rstrip("/")


def a1111_models(img_cfg: ImageConfig) -> list[str]:
    """Probe the server (it may be asleep) and list its models."""
    url = _a1111_url(img_cfg)
    try:
        r = httpx.get(f"{url}/sdapi/v1/sd-models", timeout=10)
    except httpx.HTTPError as e:
        raise AIError(f"The image server at {url} isn't reachable (is it asleep?): {e}") from e
    if r.status_code != 200:
        raise AIError(f"The image server at {url} answered {r.status_code}.")
    try:
        return [m.get("model_name") or m.get("title") or "?" for m in r.json()]
    except (ValueError, AttributeError) as e:
        raise AIError(f"{url} doesn't look like an AUTOMATIC1111-compatible server.") from e


def _paint_a1111(img_cfg: ImageConfig, prompt: str) -> bytes:
    url = _a1111_url(img_cfg)
    payload: dict = {
        "prompt": prompt,
        "negative_prompt": A1111_NEGATIVE,
        "width": A1111_SIZE,
        "height": A1111_SIZE,
        "steps": img_cfg.steps,
        "cfg_scale": img_cfg.cfg_scale,
        "seed": random.randint(1, 2**31 - 1),  # a fresh seed, so "New icon" differs
        "batch_size": 1,
        "n_iter": 1,
    }
    if img_cfg.model:
        payload["override_settings"] = {"sd_model_checkpoint": img_cfg.model}
    try:
        # Painting can take minutes; connecting should not (a sleeping laptop fails fast).
        r = httpx.post(
            f"{url}/sdapi/v1/txt2img", json=payload, timeout=httpx.Timeout(600, connect=10)
        )
    except httpx.HTTPError as e:
        raise AIError(f"The image server at {url} isn't reachable (is it asleep?): {e}") from e
    if r.status_code != 200:
        raise AIError(f"Image server error ({r.status_code}): {r.text[:300]}")
    try:
        data = (r.json().get("images") or [None])[0]
    except ValueError as e:
        raise AIError("The image server returned something that isn't JSON.") from e
    if not data:
        raise AIError("The image server returned no image.")
    return base64.b64decode(data.split(",", 1)[-1])


def check_ready(ai_cfg: AIConfig, img_cfg: ImageConfig) -> str | None:
    """Why icons can't be made right now, or None if they can."""
    match img_cfg.provider:
        case "none":
            return "Recipe icons are turned off."
        case "svg":
            return None if ai_cfg.enabled else "Set up an AI model first; it draws the icons."
        case "a1111":
            return None if img_cfg.base_url else "Set the Stable Diffusion server address."
        case "openai":
            if ai_cfg.openai_api_key or ai_cfg.openai_base_url:
                return None
            return "Add an OpenAI API key under AI model."
        case "google":
            return None if ai_cfg.google_api_key else "Add a Google API key under AI model."
    return "Unknown icon engine."


QA_SCHEMA = {
    "type": "object",
    "properties": {"has_text": {"type": "boolean"}},
    "required": ["has_text"],
    "additionalProperties": False,
}
PAINT_ATTEMPTS = 3


def has_stray_text(ai_cfg: AIConfig, png: bytes) -> bool | None:
    """Ask the AI model (if it can see images) whether a painted icon contains text.

    Returns None when there is no model to ask or it can't look at images.
    """
    if not ai_cfg.enabled:
        return None
    try:
        img = Image.open(io.BytesIO(png)).convert("RGB")
        img.thumbnail((384, 384))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        res = get_provider(ai_cfg).complete_json(
            "You check small food illustrations for a recipe app. Reply with JSON only.",
            "Does this picture contain any visible text: letters, words, numbers, a title, "
            "a caption or a logo? Food shapes and decorations are not text.",
            QA_SCHEMA,
            "icon_qa",
            images=[("image/png", buf.getvalue())],
        )
        return bool(res.get("has_text"))
    except Exception as e:  # noqa: BLE001 - a model without vision just skips the check
        log.info("Icon text check skipped: %s", e)
        return None


def _paint(ai_cfg: AIConfig, img_cfg: ImageConfig, subject: str) -> bytes:
    model = img_cfg.effective_model or ""
    if img_cfg.provider == "a1111":
        return _paint_a1111(img_cfg, a1111_prompt(subject))
    if img_cfg.provider == "openai":
        return _paint_openai(ai_cfg, model, raster_prompt(subject))
    return _paint_google(ai_cfg, model, raster_prompt(subject))


def make_icon_png(ai_cfg: AIConfig, img_cfg: ImageConfig, r: Recipe) -> bytes:
    problem = check_ready(ai_cfg, img_cfg)
    if problem:
        raise AIError(problem)
    if img_cfg.provider == "svg":
        return _draw_svg(ai_cfg, img_cfg, describe(r))
    subject = food_subject(r)
    # Image models sometimes paint words anyway; if the AI model can look, repaint (each
    # try uses a new seed) and keep the last attempt if text keeps appearing.
    png = b""
    for _ in range(PAINT_ATTEMPTS):
        png = _paint(ai_cfg, img_cfg, subject)
        if not has_stray_text(ai_cfg, png):
            break
        log.info("Icon for %r had text in it; painting it again", r.title)
    return png


def _store(png: bytes) -> str:
    try:
        Image.open(io.BytesIO(png)).verify()
    except Exception as e:  # noqa: BLE001
        raise AIError("The icon engine returned something that isn't an image.") from e
    name = images.save_image_bytes(png, png=True, max_dim=SIZE)
    if not name:
        raise AIError("Could not save the icon.")
    return name


def apply_icon(db: Session, r: Recipe, *, replace_photo: bool = False) -> None:
    """Make an icon for ``r`` and attach it, replacing any earlier icon."""
    if r.image and not r.image_generated and not replace_photo:
        raise AIError("This recipe has a photo.")
    png = make_icon_png(load_ai_config(db), load_image_config(db), r)
    name = _store(png)
    images.delete_image(r.image)
    r.image, r.image_generated = name, True


def _load(db: Session, recipe_id: int) -> Recipe | None:
    return db.scalar(
        select(Recipe)
        .where(Recipe.id == recipe_id)
        .options(selectinload(Recipe.ingredients), selectinload(Recipe.tags))
    )


# ---- Background work ---------------------------------------------------------

# One icon at a time: keeps local models responsive and paid APIs within rate limits.
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="icons")


def _auto_icon(recipe_id: int) -> None:
    try:
        with session_scope() as db:
            r = _load(db, recipe_id)
            if r is None or r.image:
                return
            apply_icon(db, r)
    except AIError as e:
        log.info("Automatic icon for recipe %s skipped: %s", recipe_id, e)
    except Exception:
        log.exception("Automatic icon for recipe %s failed", recipe_id)


def maybe_auto_icon(recipe_id: int) -> None:
    """Queue an icon for a newly added (committed) recipe without a photo, if enabled."""
    with session_scope() as db:
        r = db.get(Recipe, recipe_id)
        if r is None or r.image:
            return
        img_cfg = load_image_config(db)
        if not img_cfg.auto or check_ready(load_ai_config(db), img_cfg):
            return
    _pool.submit(_auto_icon, recipe_id)


def targets(db: Session, scope: str) -> list[int]:
    q = select(Recipe.id).order_by(Recipe.id)
    if scope == "all":
        q = q.where((Recipe.image.is_(None)) | (Recipe.image_generated.is_(True)))
    else:
        q = q.where(Recipe.image.is_(None))
    return list(db.scalars(q))


MAX_FAILURES_IN_A_ROW = 3


def _run_job(job_id: int, recipe_ids: list[int]) -> None:
    from .importer import _log

    with session_scope() as db:
        job = db.get(ImportJob, job_id)
        job.status, job.total = "running", len(recipe_ids)
        db.commit()
        img_cfg = load_image_config(db)
        if img_cfg.provider == "a1111":
            # Check once that the server is awake rather than failing every recipe slowly.
            a1111_models(img_cfg)
        streak = 0
        for rid in recipe_ids:
            if streak >= MAX_FAILURES_IN_A_ROW:
                _log(
                    job,
                    f"Stopped after {streak} failures in a row. Fix the problem and run it again; "
                    "recipes that already have an icon are skipped.",
                )
                job.status = "failed"
                db.commit()
                return
            r = _load(db, rid)
            if r is None or (r.image and not r.image_generated):
                job.processed += 1  # deleted, or a photo was added meanwhile
                db.commit()
                continue
            title = r.title
            try:
                apply_icon(db, r)
                job.imported += 1
                streak = 0
                _log(job, f"ok    {title}")
            except Exception as e:  # noqa: BLE001 - one failure shouldn't stop the batch
                db.rollback()
                job = db.get(ImportJob, job_id)
                job.failed += 1
                streak += 1
                _log(job, f"FAIL  {title}: {e}")
            job.processed += 1
            db.commit()
        job.status = "done"


def start_job(job_id: int, recipe_ids: list[int]) -> None:
    from .importer import _guard

    threading.Thread(target=_guard, args=(_run_job, job_id, recipe_ids), daemon=True).start()


def run_job_sync(job_id: int, recipe_ids: list[int]) -> None:
    from .importer import _guard

    _guard(_run_job, job_id, recipe_ids)
