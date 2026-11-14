# Changelog

## Unreleased

- Recipe icons: recipes without a photo can get a simple AI-made icon in the style of the app's logo, drawn as SVG by the configured AI model (any provider, including Ollama), painted by a local Stable Diffusion server with the AUTOMATIC1111 API (A1111, Forge, sd-server), or by an OpenAI or Google image model. For painted icons, the AI model describes how the dish looks, then a vision-capable model checks each icon for stray text and for whether it shows the dish, repainting if needed. Make one per recipe, all missing ones at once from Settings, or automatically for new recipes. New settings `COLLANDER_IMAGE_PROVIDER`, `COLLANDER_IMAGE_MODEL`, `COLLANDER_IMAGE_BASE_URL`, `COLLANDER_IMAGE_STEPS` and `COLLANDER_IMAGE_CFG_SCALE`.
- Settings shows the version and commit of the running build.
- `COLLANDER_DATA_VOLUME` chooses the data volume or folder without editing `compose.yaml`.
- Frontend dependency updates for security alerts (React Router 7, Vite 6.4, Vitest 5).

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
