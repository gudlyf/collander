"""Application configuration, read from environment variables (prefix ``COLLANDER_``)."""

from __future__ import annotations

import contextlib
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COLLANDER_", env_file=".env", extra="ignore")

    # Where the SQLite database, images and uploaded import files live.
    data_dir: Path = Path("./data")

    # Optional: set the login password from the environment instead of the first-run setup page.
    # When set, it always wins over a password stored in the database.
    password: str | None = None

    # Optional: fixed session secret. If unset, one is generated and stored in the data dir.
    secret_key: str | None = None

    # Session lifetime in days.
    session_days: int = 30

    # Set to true when serving over HTTPS so the session cookie is marked Secure.
    secure_cookies: bool = False

    # Directory containing the built frontend (index.html + assets). Optional in dev.
    static_dir: Path | None = None

    # Maximum upload size for imports (bytes).
    max_upload_bytes: int = 512 * 1024 * 1024

    # Number of background workers processing the photo/URL/text import queue.
    queue_workers: int = 2

    # AI defaults (can be overridden from the Settings page; API keys in env always win).
    ai_provider: str = "none"  # none | anthropic | openai | google | ollama
    ai_model: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    google_api_key: str | None = None
    ollama_base_url: str = "http://host.docker.internal:11434"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "collander.db"

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def queue_dir(self) -> Path:
        return self.data_dir / "queue"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.images_dir, self.uploads_dir, self.queue_dir):
            d.mkdir(parents=True, exist_ok=True)

    def get_secret_key(self) -> str:
        if self.secret_key:
            return self.secret_key
        path = self.data_dir / "secret_key"
        if path.exists():
            return path.read_text().strip()
        self.ensure_dirs()
        key = secrets.token_urlsafe(48)
        path.write_text(key)
        with contextlib.suppress(OSError):
            path.chmod(0o600)
        return key


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s
