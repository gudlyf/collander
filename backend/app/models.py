"""SQLAlchemy ORM models.

Design notes
------------
* Ingredient and step rows keep the *original* text untouched. A modification is
  stored alongside it (``override_text`` / ``omitted``), so the UI can always show
  both what the source said and what you actually do.
* Rows with ``is_addition`` are things you added that were not in the original.
* Scaling (2x, 1/2x, ...) is applied at display time only and never persisted.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


recipe_tags = Table(
    "recipe_tags",
    Base.metadata,
    Column("recipe_id", ForeignKey("recipes.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Recipe(Base):
    __tablename__ = "recipes"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    source_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # How the recipe got here: manual | url | text | evernote | bundle | gdrive
    source_kind: Mapped[str] = mapped_column(String(30), default="manual")
    servings: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prep_time: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cook_time: Mapped[str | None] = mapped_column(String(100), nullable=True)
    total_time: Mapped[str | None] = mapped_column(String(100), nullable=True)
    image: Mapped[str | None] = mapped_column(String(300), nullable=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    # Free-form original text for imports that could not be fully structured.
    original_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    ingredients: Mapped[list[Ingredient]] = relationship(
        back_populates="recipe",
        cascade="all, delete-orphan",
        order_by="Ingredient.position",
    )
    steps: Mapped[list[Step]] = relationship(
        back_populates="recipe",
        cascade="all, delete-orphan",
        order_by="Step.position",
    )
    notes: Mapped[list[Note]] = relationship(
        back_populates="recipe",
        cascade="all, delete-orphan",
        order_by="Note.created_at.desc()",
    )
    tags: Mapped[list[Tag]] = relationship(secondary=recipe_tags, back_populates="recipes")


class Ingredient(Base):
    __tablename__ = "ingredients"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    section: Mapped[str | None] = mapped_column(String(200), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    override_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    override_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    omitted: Mapped[bool] = mapped_column(Boolean, default=False)
    is_addition: Mapped[bool] = mapped_column(Boolean, default=False)

    recipe: Mapped[Recipe] = relationship(back_populates="ingredients")


class Step(Base):
    __tablename__ = "steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    section: Mapped[str | None] = mapped_column(String(200), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    override_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    override_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    omitted: Mapped[bool] = mapped_column(Boolean, default=False)
    is_addition: Mapped[bool] = mapped_column(Boolean, default=False)

    recipe: Mapped[Recipe] = relationship(back_populates="steps")


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    recipe: Mapped[Recipe] = relationship(back_populates="notes")


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)

    recipes: Mapped[list[Recipe]] = relationship(secondary=recipe_tags, back_populates="tags")


class AppSetting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30))  # evernote | bundle
    status: Mapped[str] = mapped_column(String(30), default="pending")
    # pending | parsed | running | done | failed
    filename: Mapped[str] = mapped_column(String(500))
    stored_path: Mapped[str] = mapped_column(String(1000))
    total: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    imported: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    use_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    log: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class QueueItem(Base):
    """A single photo/URL/text import processed in the background."""

    __tablename__ = "import_queue"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))  # photo | url | text
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    # queued | processing | done | failed
    label: Mapped[str] = mapped_column(String(500), default="")
    input_json: Mapped[str] = mapped_column(Text, default="{}")
    file_count: Mapped[int] = mapped_column(Integer, default=0)
    recipe_id: Mapped[int | None] = mapped_column(
        ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    method: Mapped[str | None] = mapped_column(String(30), nullable=True)
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
