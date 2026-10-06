"""Gemini API client — fast drop-in replacement for MedGemmaClient.

Uses google-generativeai (Gemini Flash) via a simple API call.
No local model loading, no GPU, responses in ~1 second.

Set env var MODEL_BACKEND=gemini and GEMINI_API_KEY=your_key.
"""

from __future__ import annotations
import os


class GeminiClient:
    """Wraps Gemini Flash with the same chat() interface as MedGemmaClient."""

    def __init__(self) -> None:
        self._model = None

    def _load(self) -> None:
        if self._model is not None:
            return
        import google.generativeai as genai
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY environment variable not set")
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel("gemini-2.0-flash")

    def chat(self, messages: list[dict], max_new_tokens: int = 512, temperature: float = 0.3) -> str:
        """Accept OpenAI-style message list, return assistant reply string."""
        self._load()
        import google.generativeai as genai

        # Extract system prompt if present
        system = next((m["content"] for m in messages if m["role"] == "system"), None)
        history = [m for m in messages if m["role"] != "system"]

        model = (
            genai.GenerativeModel("gemini-2.0-flash", system_instruction=system)
            if system else self._model
        )

        # Convert to Gemini's format: alternating user/model turns
        gemini_history = []
        for m in history[:-1]:
            role = "model" if m["role"] == "assistant" else "user"
            gemini_history.append({"role": role, "parts": [m["content"]]})

        last_user = history[-1]["content"] if history else ""

        chat = model.start_chat(history=gemini_history)
        response = chat.send_message(
            last_user,
            generation_config={"max_output_tokens": max_new_tokens, "temperature": temperature},
        )
        return response.text.strip()
