"""Full-text search backed by SQLite FTS5.

Query syntax (all terms are ANDed together):

* ``chicken curry``       - both words (prefix + stemming: "tomato" finds "tomatoes")
* ``"brown butter"``      - exact phrase
* ``-cilantro``           - exclude recipes mentioning a word
* ``tag:vegetarian``      - must have the tag (``-tag:spicy`` excludes it)
* ``is:favorite`` / ``is:modified`` / ``is:review`` - status filters
* ``in:title soup``       - restrict following words to a field: title, ingredients, tags, body

Results are ranked by BM25 with title and tags weighted above ingredients, which
are weighted above steps/notes.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..models import Recipe

FTS_COLUMNS = ("title", "tags", "ingredients", "body")
# BM25 column weights, in FTS_COLUMNS order (recipe_id is UNINDEXED but still counts).
_WEIGHTS = "0, 10.0, 6.0, 4.0, 1.0"

CREATE_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS recipe_fts USING fts5(
    recipe_id UNINDEXED,
    title,
    tags,
    ingredients,
    body,
    tokenize = 'porter unicode61 remove_diacritics 2'
)
"""


def _doc(r: Recipe) -> dict:
    ings = []
    for i in r.ingredients:
        ings.append(i.text)
        if i.override_text:
            ings.append(i.override_text)
    body = [r.description or ""]
    for s in r.steps:
        body.append(s.text)
        if s.override_text:
            body.append(s.override_text)
    body.extend(n.text for n in r.notes)
    if r.original_text:
        body.append(r.original_text)
    if r.source_name:
        body.append(r.source_name)
    return {
        "recipe_id": r.id,
        "title": r.title,
        "tags": " ".join(t.name.replace("-", " ") + " " + t.name for t in r.tags),
        "ingredients": "\n".join(ings),
        "body": "\n".join(body),
    }


def ensure_index(db: Session) -> None:
    db.execute(text(CREATE_SQL))


def index_recipe(db: Session, r: Recipe) -> None:
    remove_recipe(db, r.id)
    db.execute(
        text(
            "INSERT INTO recipe_fts (recipe_id, title, tags, ingredients, body) "
            "VALUES (:recipe_id, :title, :tags, :ingredients, :body)"
        ),
        _doc(r),
    )


def remove_recipe(db: Session, recipe_id: int) -> None:
    db.execute(text("DELETE FROM recipe_fts WHERE recipe_id = :id"), {"id": recipe_id})


def rebuild(db: Session) -> int:
    db.execute(text("DELETE FROM recipe_fts"))
    n = 0
    for r in db.query(Recipe).all():
        index_recipe(db, r)
        n += 1
    return n


@dataclass
class ParsedQuery:
    match: str | None = None  # FTS5 MATCH expression recipes must satisfy
    exclude_match: str | None = None  # FTS5 MATCH expression recipes must NOT satisfy
    tags: list[str] = field(default_factory=list)
    exclude_tags: list[str] = field(default_factory=list)
    flags: set[str] = field(default_factory=set)


_FIELD_ALIASES = {
    "title": "title",
    "ingredient": "ingredients",
    "ingredients": "ingredients",
    "tag": "tags",
    "tags": "tags",
    "body": "body",
    "steps": "body",
    "notes": "body",
}


def _fts_term(word: str, prefix: bool) -> str | None:
    # Keep letters/digits; FTS5 syntax characters are stripped to avoid query errors.
    tokens = re.findall(r"\w+", word, flags=re.UNICODE)
    if not tokens:
        return None
    if len(tokens) == 1:
        return f'"{tokens[0]}"' + ("*" if prefix else "")
    return '"' + " ".join(tokens) + '"'


def parse_query(q: str) -> ParsedQuery:
    from .tags import normalize_tag

    pq = ParsedQuery()
    try:
        parts = shlex.split(q)
    except ValueError:  # unbalanced quotes
        parts = q.replace('"', " ").split()
    # Detect which parts were quoted phrases so we don't prefix-match them.
    quoted = set(re.findall(r'"([^"]+)"', q))

    positives: list[str] = []
    negatives: list[str] = []
    column: str | None = None
    for part in parts:
        neg = part.startswith("-") and len(part) > 1
        body = part[1:] if neg else part
        low = body.lower()
        if low.startswith("tag:"):
            t = normalize_tag(body[4:])
            if t:
                (pq.exclude_tags if neg else pq.tags).append(t)
            continue
        if low.startswith("is:"):
            pq.flags.add(low[3:])
            continue
        if low.startswith("in:"):
            column = _FIELD_ALIASES.get(low[3:])
            continue
        term = _fts_term(body, prefix=body not in quoted)
        if not term:
            continue
        if column:
            term = f"{column} : {term}"
        (negatives if neg else positives).append(term)

    if positives:
        pq.match = " AND ".join(positives)
    if negatives:
        # Applied as a set difference so "-cilantro" works even without positive terms.
        pq.exclude_match = " OR ".join(negatives)
    return pq


def search_ids(db: Session, match: str) -> list[tuple[int, float]]:
    rows = db.execute(
        text(
            f"SELECT recipe_id, bm25(recipe_fts, {_WEIGHTS}) AS score FROM recipe_fts "
            "WHERE recipe_fts MATCH :q ORDER BY score"
        ),
        {"q": match},
    ).all()
    return [(int(r[0]), float(r[1])) for r in rows]


def matching_ids(db: Session, match: str) -> set[int]:
    rows = db.execute(
        text("SELECT recipe_id FROM recipe_fts WHERE recipe_fts MATCH :q"), {"q": match}
    ).all()
    return {int(r[0]) for r in rows}


def snippet(db: Session, recipe_id: int, match: str) -> str | None:
    row = db.execute(
        text(
            "SELECT snippet(recipe_fts, -1, char(2), char(3), '…', 12) FROM recipe_fts "
            "WHERE recipe_fts MATCH :q AND recipe_id = :id"
        ),
        {"q": match, "id": recipe_id},
    ).first()
    return row[0] if row else None
