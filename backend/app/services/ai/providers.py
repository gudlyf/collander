"""LLM provider backends.

Every provider implements one operation: given a system prompt, a user prompt and
a JSON schema, return a parsed JSON object that matches the schema. Higher-level
features (recipe extraction, tagging) live in ``tasks.py`` and are provider-agnostic.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any, Protocol

import httpx

from ..settings_store import AIConfig

log = logging.getLogger(__name__)

# Claude models that accept the server-side refusal fallback parameter.
_ANTHROPIC_FALLBACK_MODELS = {
    "claude-fable-5-2",
    "claude-fable-5-1",
    "claude-opus-5-5",
    "claude-opus-5",
    "claude-sonnet-5-5",
}


class AIError(RuntimeError):
    pass


class AIFormatError(AIError):
    """The model answered, but not in the expected shape (worth one retry)."""


# An image passed to a vision-capable model: (mime type, raw bytes).
ImageInput = tuple[str, bytes]


class Provider(Protocol):
    def complete_json(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        name: str,
        images: list[ImageInput] | None = None,
    ) -> dict: ...


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _loads(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise AIFormatError(f"Model did not return valid JSON: {e}") from e


class AnthropicProvider:
    def __init__(self, cfg: AIConfig):
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=cfg.anthropic_api_key, timeout=300, max_retries=2)
        self.model = cfg.effective_model

    def complete_json(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        name: str,
        images: list[ImageInput] | None = None,
    ) -> dict:
        anthropic = self._anthropic
        content: list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": mime, "data": _b64(data)},
            }
            for mime, data in images or []
        ]
        content.append({"type": "text", "text": user})
        kwargs: dict[str, Any] = dict(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": content}],
            # Extraction and tagging are simple tasks: low effort keeps them fast and cheap.
            output_config={"format": {"type": "json_schema", "schema": schema}, "effort": "low"},
        )
        try:
            if self.model in _ANTHROPIC_FALLBACK_MODELS:
                # If a safety classifier declines, let the API re-run on a fallback model.
                resp = self.client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
                )
            else:
                resp = self.client.messages.create(**kwargs)
        except anthropic.AuthenticationError as e:
            raise AIError("Anthropic rejected the API key.") from e
        except anthropic.NotFoundError as e:
            raise AIError(f"Anthropic model not found: {self.model}") from e
        except anthropic.BadRequestError as e:
            raise AIError(f"Anthropic request error: {e.message}") from e
        except anthropic.RateLimitError as e:
            raise AIError("Anthropic rate limit hit; try again shortly.") from e
        except anthropic.APIStatusError as e:
            raise AIError(f"Anthropic API error ({e.status_code}): {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise AIError("Could not reach the Anthropic API.") from e

        if resp.stop_reason == "refusal":
            raise AIError("The model declined to process this content.")
        if resp.stop_reason == "max_tokens":
            raise AIError("The model ran out of output tokens; the source may be too long.")
        text = next((b.text for b in resp.content if b.type == "text"), "")
        return _loads(text)


class OpenAIProvider:
    def __init__(self, cfg: AIConfig):
        import openai

        self._openai = openai
        self.client = openai.OpenAI(
            api_key=cfg.openai_api_key or "not-needed",
            base_url=cfg.openai_base_url or None,
            timeout=300,
            max_retries=2,
        )
        self.model = cfg.effective_model

    def complete_json(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        name: str,
        images: list[ImageInput] | None = None,
    ) -> dict:
        openai = self._openai
        user_content: Any = user
        if images:
            user_content = [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{_b64(data)}"}}
                for mime, data in images
            ] + [{"type": "text", "text": user}]
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": name, "schema": schema, "strict": True},
                },
            )
        except openai.AuthenticationError as e:
            raise AIError("OpenAI rejected the API key.") from e
        except openai.NotFoundError as e:
            raise AIError(f"OpenAI model not found: {self.model}") from e
        except openai.APIStatusError as e:
            raise AIError(f"OpenAI API error ({e.status_code}): {e.message}") from e
        except openai.APIConnectionError as e:
            raise AIError("Could not reach the OpenAI API.") from e
        choice = resp.choices[0]
        if getattr(choice.message, "refusal", None):
            raise AIError("The model declined to process this content.")
        return _loads(choice.message.content or "")


class GoogleProvider:
    def __init__(self, cfg: AIConfig):
        from google import genai

        self.client = genai.Client(api_key=cfg.google_api_key)
        self.model = cfg.effective_model

    def complete_json(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        name: str,
        images: list[ImageInput] | None = None,
    ) -> dict:
        from google.genai import errors, types

        contents: list[Any] = [
            types.Part.from_bytes(data=data, mime_type=mime) for mime, data in images or []
        ]
        contents.append(user)
        try:
            resp = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_json_schema=schema,
                ),
            )
        except errors.APIError as e:
            raise AIError(f"Google AI error ({e.code}): {e.message}") from e
        return _loads(resp.text or "")


class OllamaProvider:
    def __init__(self, cfg: AIConfig):
        self.base_url = cfg.ollama_base_url.rstrip("/")
        self.model = cfg.effective_model

    def complete_json(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        name: str,
        images: list[ImageInput] | None = None,
    ) -> dict:
        try:
            r = httpx.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "stream": False,
                    "format": schema,
                    "options": {"temperature": 0},
                    "messages": [
                        {"role": "system", "content": system},
                        {
                            "role": "user",
                            "content": user,
                            **({"images": [_b64(d) for _, d in images]} if images else {}),
                        },
                    ],
                },
                timeout=600,
            )
        except httpx.HTTPError as e:
            raise AIError(f"Could not reach Ollama at {self.base_url}: {e}") from e
        if r.status_code != 200:
            raise AIError(f"Ollama error ({r.status_code}): {r.text[:300]}")
        return _loads(r.json().get("message", {}).get("content", ""))


def get_provider(cfg: AIConfig) -> Provider:
    if not cfg.enabled:
        raise AIError("AI is not configured. Choose a provider on the Settings page.")
    match cfg.provider:
        case "anthropic":
            return AnthropicProvider(cfg)
        case "openai":
            return OpenAIProvider(cfg)
        case "google":
            return GoogleProvider(cfg)
        case "ollama":
            return OllamaProvider(cfg)
    raise AIError(f"Unknown AI provider: {cfg.provider}")
