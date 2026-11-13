"""Recipe image storage: download, decode, resize and save under ``data/images``."""

from __future__ import annotations

import base64
import io
import logging
import re
import uuid

import httpx
from PIL import Image, ImageOps

from ..config import get_settings
from .fetch import USER_AGENT, assert_public_url

log = logging.getLogger(__name__)

MAX_DIM = 1600
MAX_BYTES = 25 * 1024 * 1024
_NAME_RE = re.compile(r"^[0-9a-f]{32}\.(jpg|png|webp)$")


def is_stored_name(value: str | None) -> bool:
    return bool(value and _NAME_RE.match(value))


def save_image_bytes(data: bytes) -> str | None:
    """Normalize to JPEG/PNG (max 1600px) and store. Returns the stored file name."""
    if not data or len(data) > MAX_BYTES:
        return None
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)
        img.thumbnail((MAX_DIM, MAX_DIM))
    except Exception as e:  # noqa: BLE001 - any decode failure just means "no image"
        log.info("Could not decode image: %s", e)
        return None
    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    ext = "png" if has_alpha else "jpg"
    name = f"{uuid.uuid4().hex}.{ext}"
    path = get_settings().images_dir / name
    if ext == "jpg":
        img.convert("RGB").save(path, "JPEG", quality=85, optimize=True)
    else:
        img.save(path, "PNG", optimize=True)
    return name


def save_image_from_url(url: str) -> str | None:
    try:
        assert_public_url(url)
        with httpx.Client(
            follow_redirects=True, timeout=30, headers={"User-Agent": USER_AGENT}
        ) as client:
            r = client.get(url)
            if r.status_code != 200:
                return None
            return save_image_bytes(r.content)
    except Exception as e:  # noqa: BLE001
        log.info("Image download failed for %s: %s", url, e)
        return None


def save_image_from_data_uri(uri: str) -> str | None:
    m = re.match(r"^data:image/[\w.+-]+;base64,(.*)$", uri, re.DOTALL)
    if not m:
        return None
    try:
        return save_image_bytes(base64.b64decode(m.group(1)))
    except ValueError:
        return None


def resolve_image(value: str | None) -> str | None:
    """Turn an incoming image reference into a stored image name (or None)."""
    if not value:
        return None
    if is_stored_name(value):
        return value if (get_settings().images_dir / value).exists() else None
    if value.startswith("data:"):
        return save_image_from_data_uri(value)
    if value.startswith(("http://", "https://")):
        return save_image_from_url(value)
    return None


def delete_image(name: str | None) -> None:
    if is_stored_name(name):
        (get_settings().images_dir / name).unlink(missing_ok=True)


def image_as_data_uri(name: str | None) -> str | None:
    if not is_stored_name(name):
        return None
    path = get_settings().images_dir / name
    if not path.exists():
        return None
    mime = "image/png" if name.endswith(".png") else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()
