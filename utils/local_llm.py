"""
Local LLM wrapper for Ollama (Phi-4-mini 3.8B Q4_K_M).
CPU-only on Surface Pro 4: ~15-20 tokens/sec.

Tasks routed here (never to Claude API):
  - Keyword extraction from job descriptions
  - Skills cross-reference (compare two lists)
  - Scoring breakdown (given profile + JD, assign weighted scores)
  - Fix instruction parsing (locate target bullet points)
"""
import time
from typing import Optional

import httpx

from utils.exceptions import LocalLLMError, OllamaNotAvailableError
from utils.logger import log_local_call, run_log


class LocalLLM:
    """
    Async wrapper for Ollama local inference.
    Call unload() before WriterAgent's parallel API calls on 8GB systems
    to free ~3.5GB RAM. Call reload() after.
    """

    def __init__(self, config: dict):
        llm_cfg = config.get("llm", {})
        self._model = llm_cfg.get("local_model", "phi4-mini")
        self._host = llm_cfg.get("ollama_host", "http://localhost:11434")
        self._threads = llm_cfg.get("local_model_threads", 4)

    async def generate(
        self, prompt: str, max_tokens: int = 500, agent: str = "unknown"
    ) -> str:
        """Run inference. Raises OllamaNotAvailableError if server unreachable."""
        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                r = await client.post(
                    f"{self._host}/api/generate",
                    json={
                        "model": self._model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "num_predict": max_tokens,
                            "temperature": 0.1,
                            "num_thread": self._threads,
                        },
                    },
                )
                r.raise_for_status()
                data = r.json()
                response_text = data.get("response", "")

                duration_ms = (time.monotonic() - start) * 1000
                log_local_call(
                    agent=agent,
                    model=self._model,
                    prompt_chars=len(prompt),
                    response_chars=len(response_text),
                    duration_ms=duration_ms,
                )
                return response_text

        except httpx.ConnectError:
            raise OllamaNotAvailableError(
                f"Ollama server not reachable at {self._host}"
            )
        except httpx.HTTPStatusError as exc:
            raise LocalLLMError(
                f"Ollama HTTP {exc.response.status_code}: {exc}",
                agent=agent,
            )
        except OllamaNotAvailableError:
            raise
        except Exception as exc:
            raise LocalLLMError(f"Local LLM call failed: {exc}", agent=agent)

    async def unload(self) -> None:
        """
        Free model memory before Writer Agent's parallel API calls.
        Frees ~3.5GB on 8GB systems. Best-effort — never raises.
        """
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"{self._host}/api/generate",
                    json={"model": self._model, "keep_alive": 0},
                )
            run_log("INFO", "local_llm", f"Model {self._model} unloaded from memory")
        except Exception:
            pass

    async def reload(self) -> None:
        """Warm up model after Writer Agent completes. Best-effort — never raises."""
        try:
            await self.generate("Ready", max_tokens=5, agent="system")
            run_log("INFO", "local_llm", f"Model {self._model} reloaded")
        except Exception:
            pass

    async def is_available(self) -> bool:
        """Check if Ollama server is running (health check and --no-local-model guard)."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{self._host}/api/tags")
                return r.status_code == 200
        except Exception:
            return False
