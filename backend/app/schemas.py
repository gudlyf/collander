"""Pydantic schemas.

``RecipeIn`` is the single interchange format used everywhere: the editor, AI
extraction, URL scraping, Evernote/Google Drive imports and backup bundles.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

BUNDLE_FORMAT = "collander-bundle"
BUNDLE_VERSION = 1


class IngredientIn(BaseModel):
    text: str
    section: str | None = None
    override_text: str | None = None
    override_note: str | None = None
    omitted: bool = False
    is_addition: bool = False


class StepIn(BaseModel):
    text: str
    section: str | None = None
    override_text: str | None = None
    override_note: str | None = None
    omitted: bool = False
    is_addition: bool = False


class NoteIn(BaseModel):
    text: str
    created_at: datetime | None = None


class RecipeIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    source_url: str | None = None
    source_name: str | None = None
    source_kind: str = "manual"
    servings: str | None = None
    prep_time: str | None = None
    cook_time: str | None = None
    total_time: str | None = None
    rating: int | None = Field(default=None, ge=0, le=5)
    favorite: bool = False
    needs_review: bool = False
    original_text: str | None = None
    tags: list[str] = []
    ingredients: list[IngredientIn] = []
    steps: list[StepIn] = []
    notes: list[NoteIn] = []
    # One of: existing stored image name (unchanged), an http(s) URL to download,
    # or a data: URI (used by bundles / Evernote). None removes the image.
    image: str | None = None
    created_at: datetime | None = None
    # Set by importers only; not exposed in the editor.
    import_key: str | None = Field(default=None, exclude=True)


class IngredientOut(IngredientIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class StepOut(StepIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    text: str
    created_at: datetime
    updated_at: datetime


class RecipeSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    description: str
    image: str | None
    favorite: bool
    rating: int | None
    needs_review: bool
    total_time: str | None
    tags: list[str]
    has_modifications: bool
    updated_at: datetime
    snippet: str | None = None


class RecipeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    description: str
    source_url: str | None
    source_name: str | None
    source_kind: str
    servings: str | None
    prep_time: str | None
    cook_time: str | None
    total_time: str | None
    image: str | None
    rating: int | None
    favorite: bool
    needs_review: bool
    original_text: str | None
    tags: list[str]
    ingredients: list[IngredientOut]
    steps: list[StepOut]
    notes: list[NoteOut]
    created_at: datetime
    updated_at: datetime


class RecipeList(BaseModel):
    items: list[RecipeSummary]
    total: int


class TagOut(BaseModel):
    id: int
    name: str
    count: int


class TagRename(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class Bundle(BaseModel):
    format: str = BUNDLE_FORMAT
    version: int = BUNDLE_VERSION
    recipes: list[RecipeIn]


# ---- Imports -------------------------------------------------------------


class DraftResponse(BaseModel):
    recipe: RecipeIn
    method: str  # schema.org | ai | heuristic
    warnings: list[str] = []


class ImportJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    status: str
    filename: str
    total: int
    processed: int
    imported: int
    failed: int
    use_ai: bool
    log: str
    created_at: datetime


class EnexNotePreview(BaseModel):
    index: int
    title: str
    tags: list[str]
    source_url: str | None
    snippet: str
    image_count: int
    likely_recipe: bool


class EnexPreview(BaseModel):
    job: ImportJobOut
    notes: list[EnexNotePreview]


class EnexRunRequest(BaseModel):
    indexes: list[int]
    use_ai: bool = False
    extra_tags: list[str] = []


# ---- Settings / auth -----------------------------------------------------


class AISettingsOut(BaseModel):
    provider: str
    model: str | None
    ollama_base_url: str
    openai_base_url: str | None
    effective_model: str | None
    # Which providers have a key configured, and whether it came from the environment.
    keys: dict[str, str]  # provider -> "env" | "db" | ""
    auto_tag: bool


class AISettingsIn(BaseModel):
    provider: str | None = None
    model: str | None = None
    ollama_base_url: str | None = None
    openai_base_url: str | None = None
    auto_tag: bool | None = None
    # Only sent when changing; an empty string clears a stored key.
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    google_api_key: str | None = None


class AuthStatus(BaseModel):
    authenticated: bool
    setup_required: bool
    password_from_env: bool


class PasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=500)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=500)


class QueueItemOut(BaseModel):
    id: int
    kind: str
    status: str
    label: str
    file_count: int
    recipe_id: int | None
    method: str | None
    warnings: list[str]
    error: str | None
    created_at: datetime
    finished_at: datetime | None
