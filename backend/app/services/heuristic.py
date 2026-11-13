"""Best-effort recipe structuring without AI.

Looks for "Ingredients" / "Directions" style headings in plain text. When none are
found, everything goes into ``original_text`` and the recipe is flagged for review.
"""

from __future__ import annotations

import re

from ..schemas import IngredientIn, RecipeIn, StepIn

_ING_HEAD = re.compile(
    r"^\s*(ingredients?|what you(?:'ll)? need|you will need)\s*:?\s*$", re.IGNORECASE
)
_STEP_HEAD = re.compile(
    r"^\s*(directions?|instructions?|method|preparation|steps?|how to make it|procedure)\s*:?\s*$",
    re.IGNORECASE,
)
_NOTE_HEAD = re.compile(r"^\s*(notes?|tips?|variations?)\s*:?\s*$", re.IGNORECASE)
_BULLET = re.compile(r"^\s*(?:[-*•▪◦·]|\d+[.)]|step\s*\d+[:.)]?)\s*", re.IGNORECASE)
_SERVES = re.compile(r"^\s*(serves|servings|yield|makes)\s*:?\s*(.+)$", re.IGNORECASE)
_QTY_START = re.compile(
    r"^\s*([\d½⅓⅔¼¾⅛⅜⅝⅞]|a\s|an\s|one\s|two\s|three\s|pinch|dash)", re.IGNORECASE
)


def _strip_bullet(line: str) -> str:
    return _BULLET.sub("", line, count=1).strip()


def parse_text(text: str, *, title: str | None = None, source_url: str | None = None) -> RecipeIn:
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    nonblank = [ln for ln in lines if ln.strip()]
    if not title and nonblank:
        title = nonblank[0].strip()[:300]

    ingredients: list[IngredientIn] = []
    steps: list[StepIn] = []
    description: list[str] = []
    notes: list[str] = []
    servings: str | None = None
    mode = "pre"
    section: str | None = None

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if _ING_HEAD.match(line):
            mode, section = "ing", None
            continue
        if _STEP_HEAD.match(line):
            mode, section = "step", None
            continue
        if _NOTE_HEAD.match(line):
            mode = "note"
            continue
        m = _SERVES.match(line)
        if m and not servings:
            servings = m.group(2).strip()[:100]
            continue
        if mode == "pre":
            if line != title:
                description.append(line)
        elif mode == "ing":
            # A short line ending with ':' (e.g. "For the sauce:") is a section header.
            if line.endswith(":") and len(line) < 60 and not _QTY_START.match(line):
                section = line.rstrip(":").strip()
                continue
            ingredients.append(IngredientIn(text=_strip_bullet(line), section=section))
        elif mode == "step":
            if line.endswith(":") and len(line) < 60:
                section = line.rstrip(":").strip()
                continue
            steps.append(StepIn(text=_strip_bullet(line), section=section))
        else:
            notes.append(line)

    structured = bool(ingredients and steps)
    recipe = RecipeIn(
        title=title or "Untitled recipe",
        description="\n".join(description[:6]) if structured else "",
        source_url=source_url,
        servings=servings,
        ingredients=ingredients,
        steps=steps,
        needs_review=not structured,
        original_text=None if structured else text.strip(),
    )
    if notes:
        from ..schemas import NoteIn

        recipe.notes = [NoteIn(text="\n".join(notes))]
    return recipe


RECIPE_WORDS = re.compile(
    r"\b(ingredients?|directions|instructions|preheat|tablespoons?|teaspoons?|tbsp|tsp|cups?"
    r"|bake|simmer|stir|whisk|oven|servings?|serves|minutes)\b",
    re.IGNORECASE,
)


def looks_like_recipe(text: str) -> bool:
    hits = {m.group(0).lower() for m in RECIPE_WORDS.finditer(text[:20000])}
    return len(hits) >= 3
