"""Apply an AI tidy/sanity check to a recipe without losing the original.

Guards:
* quantities: the multiset of numbers across all lines must be unchanged
* content: the cleaned text may not be much shorter than the original
* modifications: lines with an override / omission / addition are never rewritten
If a guard trips, the original lines are kept and the reason is reported as an issue.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from ..schemas import IngredientIn, NoteIn, RecipeIn, StepIn
from . import ai
from .settings_store import AIConfig
from .tags import normalize_tag

_NUM = re.compile(r"\d+(?:[.,/]\d+)?|[½⅓⅔¼¾⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞]")
_CLUTTER = re.compile(r"[▢☐□•▪◦\[\]()*#_\-–—:,.\s]")
NOTE_PREFIX = "AI check:"


@dataclass
class CheckResult:
    recipe: RecipeIn
    issues: list[str] = field(default_factory=list)
    changed_lines: bool = False
    added_tags: list[str] = field(default_factory=list)


_ENUM = re.compile(r"^\s*(?:step\s*)?\d+\s*[.):]\s+", re.IGNORECASE)


def _numbers(texts: list[str]) -> Counter:
    # Leading step numbers ("1.", "Step 2:") are clutter, not quantities.
    return Counter(n.replace(",", ".") for t in texts for n in _NUM.findall(_ENUM.sub("", t)))


def _content_len(texts: list[str]) -> int:
    return sum(len(_CLUTTER.sub("", t)) for t in texts)


def _is_modified(line) -> bool:
    return bool(line.override_text or line.omitted or line.is_addition or line.override_note)


def _as_text(recipe: RecipeIn) -> str:
    out = ["Ingredients:"]
    out += [f"- {i.text}" for i in recipe.ingredients]
    out += ["", "Steps:"]
    out += [f"{n}. {s.text}" for n, s in enumerate(recipe.steps, 1)]
    return "\n".join(out)


def _comparable(old: list, new: list) -> tuple[list[str], list[str]]:
    """Texts to compare, leaving out the owner's modified lines (they are never rewritten)."""
    if any(_is_modified(x) for x in old) and len(old) == len(new):
        pairs = [(o.text, n.text) for o, n in zip(old, new, strict=True) if not _is_modified(o)]
        return [p[0] for p in pairs], [p[1] for p in pairs]
    return [x.text for x in old], [x.text for x in new]


def _merge_lines(old: list, new: list, cls) -> tuple[list, bool]:
    """Return lines to keep. Modified lines are kept verbatim."""
    has_mods = any(_is_modified(x) for x in old)
    if not has_mods:
        return [cls(text=n.text.strip(), section=n.section.strip() or None) for n in new], True
    if len(old) != len(new):
        return old, False  # can't map changes safely around the owner's edits
    merged = []
    for o, n in zip(old, new, strict=True):
        if _is_modified(o):
            merged.append(o)
        else:
            merged.append(
                o.model_copy(update={"text": n.text.strip(), "section": n.section.strip() or None})
            )
    return merged, True


def check_recipe(cfg: AIConfig, recipe: RecipeIn, existing_tags: list[str]) -> CheckResult:
    review = ai.review_recipe(cfg, recipe, existing_tags)
    res = CheckResult(recipe=recipe.model_copy(deep=True), issues=list(review.issues))
    r = res.recipe

    old_texts = [x.text for x in [*recipe.ingredients, *recipe.steps]]
    new_ings = [x for x in review.ingredients if x.text.strip()]
    new_steps = [x for x in review.steps if x.text.strip()]
    new_texts = [x.text for x in [*new_ings, *new_steps]]
    # Only lines that may actually be rewritten take part in the guards.
    cmp_old, cmp_new = _comparable(recipe.ingredients, new_ings)
    s_old, s_new = _comparable(recipe.steps, new_steps)
    cmp_old, cmp_new = cmp_old + s_old, cmp_new + s_new

    if new_texts != old_texts or [x.section or "" for x in [*new_ings, *new_steps]] != [
        x.section or "" for x in [*recipe.ingredients, *recipe.steps]
    ]:
        if _numbers(cmp_new) != _numbers(cmp_old):
            res.issues.append("Suggested cleanup changed quantities, so it was not applied.")
        elif _content_len(cmp_new) < 0.85 * _content_len(cmp_old):
            res.issues.append("Suggested cleanup removed text, so it was not applied.")
        else:
            ings, ok1 = _merge_lines(recipe.ingredients, new_ings, IngredientIn)
            steps, ok2 = _merge_lines(recipe.steps, new_steps, StepIn)
            if ok1 or ok2:
                if [x.text for x in [*ings, *steps]] != old_texts:
                    res.changed_lines = True
                    if not r.original_text:
                        r.original_text = _as_text(recipe)
                r.ingredients, r.steps = ings, steps

    for t in review.tags:
        t = normalize_tag(t)
        if t and t not in r.tags:
            r.tags.append(t)
            res.added_tags.append(t)

    # Replace any earlier AI-check note with the current findings.
    r.notes = [n for n in r.notes if not n.text.startswith(NOTE_PREFIX)]
    if res.issues:
        r.notes.append(NoteIn(text=NOTE_PREFIX + "\n" + "\n".join(f"- {i}" for i in res.issues)))
        r.needs_review = True
    return res
