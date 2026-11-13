# Changelog

## 1.0.0 (2026-11-13)

First release.

- Recipes with ingredients, steps, groups, notes, tags, ratings and favorites.
- Modifications that keep the original visible: change, leave out, or add ingredients and steps.
- Scaling (½×, 2×, 3×, custom) with kitchen-fraction formatting.
- Full-text search (SQLite FTS5) with phrases, exclusions, tag and status filters.
- Import from links (schema.org, then AI), photos (vision AI), pasted text, Evernote `.enex`, and JSON bundles.
- Background import queue for links, photos and text.
- Optional AI check: tidies formatting and flags problems without changing quantities or wording.
- AI providers: Anthropic, OpenAI and compatible servers, Google Gemini, Ollama.
- Single-password sign-in, JSON backup and restore, CLI tools.
- Multi-architecture Docker image (`linux/amd64`, `linux/arm64`) published to `ghcr.io/gudlyf/collander`, and a Compose file.
- Recipe library in card or list view.
