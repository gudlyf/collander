"""Evernote ``.enex`` export parsing.

ENEX files can be hundreds of megabytes (images are base64-encoded inline), so notes
are streamed one at a time with ``lxml.etree.iterparse``.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag
from lxml import etree

log = logging.getLogger(__name__)

_BLOCK = {
    "div",
    "p",
    "br",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "tr",
    "blockquote",
    "pre",
    "hr",
    "table",
    "ul",
    "ol",
    "section",
    "article",
}


@dataclass
class EnexResource:
    mime: str
    data: bytes
    hash: str
    filename: str | None = None


@dataclass
class EnexNote:
    index: int
    title: str
    html: str
    tags: list[str] = field(default_factory=list)
    source_url: str | None = None
    created: datetime | None = None
    resources: list[EnexResource] = field(default_factory=list)

    @property
    def text(self) -> str:
        return enml_to_text(self.html)

    @property
    def images(self) -> list[EnexResource]:
        """Image resources, in the order they appear in the note body."""
        imgs = [r for r in self.resources if r.mime.startswith("image/")]
        order = {h: i for i, h in enumerate(_media_hashes(self.html))}
        return sorted(imgs, key=lambda r: order.get(r.hash, len(order)))


_PROLOG = re.compile(r"^\s*(<\?xml[^>]*\?>)?\s*(<!DOCTYPE[^>]*>)?", re.IGNORECASE)


def _soup(html: str) -> BeautifulSoup:
    # ENML is XHTML wrapped in an XML prolog; drop the prolog and parse it as HTML.
    return BeautifulSoup(_PROLOG.sub("", html, count=1), "lxml")


def _media_hashes(html: str) -> list[str]:
    soup = _soup(html)
    return [m.get("hash", "") for m in soup.find_all("en-media")]


def enml_to_text(html: str) -> str:
    """Convert ENML/HTML to plain text, keeping line structure and list bullets."""
    if not html:
        return ""
    soup = _soup(html)
    for t in soup(["script", "style", "en-media"]):
        t.decompose()
    for todo in soup.find_all("en-todo"):
        todo.replace_with("[x] " if todo.get("checked") == "true" else "[ ] ")
    out: list[str] = []

    def walk(node):
        for child in node.children:
            if isinstance(child, NavigableString):
                out.append(str(child))
            elif isinstance(child, Tag):
                name = child.name.lower()
                if name == "li":
                    out.append("\n- ")
                elif name in _BLOCK:
                    out.append("\n")
                walk(child)
                if name in _BLOCK:
                    out.append("\n")
                elif name in ("td", "th"):
                    out.append("\t")

    walk(soup)
    lines = [" ".join(ln.replace("\xa0", " ").split()) for ln in "".join(out).splitlines()]
    text_lines: list[str] = []
    for ln in lines:
        if ln or (text_lines and text_lines[-1]):
            text_lines.append(ln)
    return "\n".join(text_lines).strip()


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%Y%m%dT%H%M%SZ")
    except ValueError:
        return None


def _text(el, path: str) -> str | None:
    found = el.find(path)
    return found.text if found is not None and found.text else None


def iter_notes(path: Path, *, with_resources: bool = True) -> Iterator[EnexNote]:
    index = 0
    context = etree.iterparse(
        str(path),
        events=("end",),
        tag="note",
        huge_tree=True,
        recover=True,
        resolve_entities=False,
        no_network=True,
    )
    for _event, el in context:
        try:
            resources: list[EnexResource] = []
            if with_resources:
                for res in el.findall("resource"):
                    data_el = res.find("data")
                    if data_el is None or not data_el.text:
                        continue
                    try:
                        raw = base64.b64decode(data_el.text)
                    except ValueError:
                        continue
                    resources.append(
                        EnexResource(
                            mime=(_text(res, "mime") or "application/octet-stream").lower(),
                            data=raw,
                            hash=hashlib.md5(raw, usedforsecurity=False).hexdigest(),
                            filename=_text(res, "resource-attributes/file-name"),
                        )
                    )
            else:
                for res in el.findall("resource"):
                    mime = (_text(res, "mime") or "").lower()
                    resources.append(EnexResource(mime=mime, data=b"", hash=""))
            yield EnexNote(
                index=index,
                title=(_text(el, "title") or "Untitled").strip(),
                html=_text(el, "content") or "",
                tags=[t.text.strip() for t in el.findall("tag") if t.text and t.text.strip()],
                source_url=_text(el, "note-attributes/source-url"),
                created=_parse_dt(_text(el, "created")),
                resources=resources,
            )
        finally:
            index += 1
            el.clear()
            while el.getprevious() is not None:
                del el.getparent()[0]
