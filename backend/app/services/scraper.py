"""Turn a URL (or pasted text) into a recipe draft.

Order of attempts:
1. schema.org Recipe metadata embedded in the page (via ``recipe-scrapers``).
2. The configured AI model, reading the page's main text.
3. A heuristic text parser (no AI configured).
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ..schemas import DraftResponse, IngredientIn, RecipeIn, StepIn
from . import ai
from .fetch import fetch_page
from .heuristic import parse_text
from .settings_store import AIConfig
from .tags import normalize_tag

log = logging.getLogger(__name__)


def _safe(fn, default=None):
    try:
        v = fn()
        return v if v not in ("", [], None) else default
    except Exception:  # noqa: BLE001 - recipe-scrapers raises many exception types
        return default


def _minutes(v) -> str | None:
    if not v:
        return None
    try:
        m = int(v)
    except (TypeError, ValueError):
        return str(v)
    if m <= 0:
        return None
    h, mm = divmod(m, 60)
    if h and mm:
        return f"{h} hr {mm} min"
    return f"{h} hr" if h else f"{mm} min"


def from_schema_org(html: str, url: str) -> RecipeIn | None:
    from recipe_scrapers import scrape_html

    try:
        s = scrape_html(html, org_url=url, supported_only=False)
    except Exception as e:  # noqa: BLE001
        log.info("schema.org parse failed for %s: %s", url, e)
        return None

    title = _safe(s.title)
    if not title:
        return None

    ingredients: list[IngredientIn] = []
    groups = _safe(s.ingredient_groups, [])
    if groups and len(groups) > 1:
        for g in groups:
            for line in g.ingredients:
                ingredients.append(IngredientIn(text=line.strip(), section=g.purpose or None))
    else:
        for line in _safe(s.ingredients, []) or []:
            if line and line.strip():
                ingredients.append(IngredientIn(text=line.strip()))

    steps = [StepIn(text=t.strip()) for t in (_safe(s.instructions_list, []) or []) if t.strip()]
    if not ingredients and not steps:
        return None

    tags: list[str] = []
    for fn in (s.category, s.cuisine):
        val = _safe(fn)
        if isinstance(val, str):
            tags.extend(x for x in val.split(",") if x.strip())
    keywords = _safe(s.keywords, []) or []
    if isinstance(keywords, list):
        tags.extend(k for k in keywords[:8] if len(k) < 30)

    return RecipeIn(
        title=title.strip()[:300],
        description=(_safe(s.description, "") or "").strip(),
        source_url=url,
        source_name=_safe(s.site_name) or urlparse(url).hostname,
        source_kind="url",
        servings=_safe(s.yields),
        prep_time=_minutes(_safe(s.prep_time)),
        cook_time=_minutes(_safe(s.cook_time)),
        total_time=_minutes(_safe(s.total_time)),
        image=_safe(s.image),
        ingredients=ingredients,
        steps=steps,
        tags=[normalize_tag(t) for t in tags if normalize_tag(t)],
    )


def page_text(html: str) -> tuple[str, str | None, str | None]:
    """Return (main text, page title, og:image) from HTML."""
    soup = BeautifulSoup(html, "lxml")
    title = soup.title.get_text(strip=True) if soup.title else None
    og = soup.find("meta", property="og:image")
    image = og.get("content") if og else None
    for tag in soup(
        ["script", "style", "noscript", "svg", "iframe", "form", "nav", "footer", "header", "aside"]
    ):
        tag.decompose()
    root = soup.find("article") or soup.find("main") or soup.body or soup
    lines = [ln.strip() for ln in root.get_text("\n").splitlines()]
    text = "\n".join(ln for ln in lines if ln)
    return text, title, image


def _merge_ai_tags(cfg: AIConfig, recipe: RecipeIn, existing: list[str], warnings: list[str]):
    try:
        suggested = ai.suggest_tags(cfg, recipe, existing)
    except ai.AIError as e:
        warnings.append(f"AI tagging failed: {e}")
        return
    for t in suggested:
        if t not in recipe.tags:
            recipe.tags.append(t)


def draft_from_url(
    url: str, cfg: AIConfig, existing_tags: list[str], use_ai: bool = True
) -> DraftResponse:
    final_url, html = fetch_page(url)
    warnings: list[str] = []
    ai_ok = use_ai and cfg.enabled

    recipe = from_schema_org(html, final_url)
    if recipe:
        # Site-provided keywords are often SEO noise; let the AI pick tags when available.
        if ai_ok and cfg.auto_tag:
            recipe.tags = []
            _merge_ai_tags(cfg, recipe, existing_tags, warnings)
        return DraftResponse(recipe=recipe, method="schema.org", warnings=warnings)

    text, title, image = page_text(html)
    host = urlparse(final_url).hostname
    if ai_ok:
        recipe, w = ai.extract_recipe(
            cfg, text, existing_tags=existing_tags, source_url=final_url, hint_title=title
        )
        warnings.extend(w)
        if recipe is None:
            raise ai.AIError("The AI could not find a recipe on that page.")
        recipe.source_kind = "url"
        recipe.source_name = host
        recipe.image = image
        return DraftResponse(recipe=recipe, method="ai", warnings=warnings)

    recipe = parse_text(text, title=title, source_url=final_url)
    recipe.source_kind = "url"
    recipe.source_name = host
    recipe.image = image
    warnings.append(
        "No structured recipe data found on the page and AI is not enabled; "
        "the result is a rough guess - please review it."
    )
    return DraftResponse(recipe=recipe, method="heuristic", warnings=warnings)


def draft_from_text(
    text: str, cfg: AIConfig, existing_tags: list[str], source_url: str | None = None
) -> DraftResponse:
    if cfg.enabled:
        recipe, warnings = ai.extract_recipe(
            cfg, text, existing_tags=existing_tags, source_url=source_url
        )
        if recipe is None:
            raise ai.AIError("The AI could not find a recipe in that text.")
        recipe.source_kind = "text"
        return DraftResponse(recipe=recipe, method="ai", warnings=warnings)
    recipe = parse_text(text, source_url=source_url)
    recipe.source_kind = "text"
    return DraftResponse(
        recipe=recipe,
        method="heuristic",
        warnings=["AI is not enabled; the text was split using headings. Please review."],
    )
