"""LLM abstraction layer.

This is the ONLY file in the entire project that imports google.genai.
Feature code must never call any LLM provider directly — always go through LLMClient.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

_MODEL_NAME = "gemma-4-26b-a4b-it"


class LLMClient:
    """Thin wrapper around the Gemini API.

    All provider-specific concerns (model name, API key, structured output) live here.
    """

    def __init__(self) -> None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY environment variable is not set. "
                "Obtain a free key from https://aistudio.google.com/app/apikey "
                "and export it before starting the server."
            )
        self._client = genai.Client(api_key=api_key)
        logger.info("LLMClient initialised with model %s", _MODEL_NAME)

    def generate(self, prompt: str) -> str:
        """Send prompt to the LLM and return plain text response.

        Raises:
            RuntimeError: if the API call fails or returns an empty response.
        """
        try:
            response = self._client.models.generate_content(
                model=_MODEL_NAME,
                contents=prompt,
            )
        except Exception as exc:
            raise RuntimeError(f"LLM API call failed: {exc}") from exc

        text = response.text
        if not text or not text.strip():
            raise RuntimeError(
                "LLM returned an empty response. "
                "The model may have blocked the request."
            )
        return text.strip()

    def generate_json(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        """Send prompt and return a structured JSON response matching the given schema.

        Gemini enforces the schema via response_mime_type + response_schema,
        so the caller receives a guaranteed-valid dict — no JSON parsing needed.

        Raises:
            RuntimeError: if the API call fails or returns an empty response.
        """
        try:
            response = self._client.models.generate_content(
                model=_MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                ),
            )
        except Exception as exc:
            raise RuntimeError(f"LLM API call failed: {exc}") from exc

        text = response.text
        if not text or not text.strip():
            raise RuntimeError(
                "LLM returned an empty response. "
                "The model may have blocked the request."
            )

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"LLM returned invalid JSON despite schema enforcement: {exc}\n"
                f"Raw response: {text!r}"
            ) from exc
