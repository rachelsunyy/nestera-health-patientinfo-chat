"""MedGemma model wrapper.

Loads the model once and exposes a simple chat() interface.
The model is loaded lazily on first use to keep imports fast.
"""

from __future__ import annotations
from config import MODEL_ID, MODEL_MAX_NEW_TOKENS, MODEL_TEMPERATURE, HF_TOKEN


class MedGemmaClient:
    """Thin wrapper around MedGemma that handles chat-template formatting.

    Heavy imports (torch, transformers) are deferred to _load() so the module
    can be imported and mocked in tests without requiring those packages.
    """

    def __init__(self) -> None:
        self._pipe = None

    def _load(self) -> None:
        if self._pipe is not None:
            return

        import torch
        from transformers import pipeline, BitsAndBytesConfig

        print(f"[MedGemma] Loading {MODEL_ID} ...")

        has_cuda = torch.cuda.is_available()
        has_mps = torch.backends.mps.is_available()

        if has_cuda:
            # NVIDIA GPU: use bfloat16, full precision on-device
            self._pipe = pipeline(
                "text-generation",
                model=MODEL_ID,
                dtype=torch.bfloat16,
                device_map="auto",
                token=HF_TOKEN,
            )
        elif has_mps:
            # Apple Silicon: load in float16 explicitly onto MPS to avoid disk offload
            from transformers import AutoTokenizer, AutoModelForCausalLM
            tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, token=HF_TOKEN)
            model = AutoModelForCausalLM.from_pretrained(
                MODEL_ID,
                torch_dtype=torch.float16,
                token=HF_TOKEN,
                low_cpu_mem_usage=True,
            ).to("mps")
            self._pipe = pipeline(
                "text-generation",
                model=model,
                tokenizer=tokenizer,
                device="mps",
            )
        else:
            # CPU fallback: float32
            self._pipe = pipeline(
                "text-generation",
                model=MODEL_ID,
                dtype=torch.float32,
                device_map="cpu",
                token=HF_TOKEN,
            )

        print("[MedGemma] Model ready.")

    def chat(
        self,
        messages: list[dict],
        max_new_tokens: int = MODEL_MAX_NEW_TOKENS,
        temperature: float = MODEL_TEMPERATURE,
    ) -> str:
        """Send a list of OpenAI-style chat messages and return the assistant reply.

        Args:
            messages: [{"role": "system"|"user"|"assistant", "content": str}, ...]
        """
        self._load()

        output = self._pipe(
            messages,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            do_sample=temperature > 0,
            return_full_text=False,
        )

        # The pipeline returns a list; the first element has 'generated_text'
        # which is itself a list of message dicts when given a chat input.
        result = output[0]["generated_text"]
        if isinstance(result, list):
            # Chat template output: list of message dicts
            return result[-1]["content"].strip()
        return str(result).strip()


# Module-level singleton — import and reuse across agents.
# Set MODEL_BACKEND=gemini to use Gemini Flash instead (fast, no GPU needed).
import os as _os
if _os.getenv("MODEL_BACKEND", "medgemma").lower() == "gemini":
    from models.gemini_client import GeminiClient as _Backend
else:
    _Backend = MedGemmaClient  # type: ignore[assignment]

client = _Backend()
