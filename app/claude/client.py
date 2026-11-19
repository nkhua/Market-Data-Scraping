from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any


@dataclass
class ClaudeClient:
    model: str
    timeout_seconds: int
    max_tokens: int

    def analyze(self, prompt: str) -> dict[str, Any]:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key or api_key == "your_anthropic_api_key_here":
            raise RuntimeError("ANTHROPIC_API_KEY is not set")

        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise RuntimeError("anthropic package is not installed") from exc

        client = Anthropic(api_key=api_key, timeout=self.timeout_seconds)
        response = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        text_blocks = [block.text for block in response.content if getattr(block, "type", "") == "text"]
        if not text_blocks:
            raise RuntimeError("Claude returned no text content")
        return json.loads(text_blocks[0])
