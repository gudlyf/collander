"""Run Alembic migrations programmatically at startup."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from .config import get_settings

_HERE = Path(__file__).resolve().parent


def alembic_config() -> Config:
    cfg = Config(str(_HERE.parent / "alembic.ini"))
    cfg.set_main_option("script_location", str(_HERE / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{get_settings().db_path}")
    return cfg


def upgrade_db() -> None:
    command.upgrade(alembic_config(), "head")
