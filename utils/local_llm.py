"""
Local LLM wrapper for Ollama (Phi-4-mini 3.8B Q4_K_M).
Used for cheap extraction/classification tasks that don't need Claude quality.
CPU-only on Surface Pro 4: ~15-20 tokens/sec.

Tasks routed here (never to Claude API):
  - Keyword extraction from job descriptions
  - Skills cross-reference (compare two lists)
  - Scoring breakdown (given profile + JD, assign weighted scores)
  - Fix instruction parsing (locate target bullet points)

Full implementation: Commit 3
"""
from typing import Optional

import httpx

from utils.logger import log_local_call, run_log
from utils.exceptions import LocalLLMError, OllamaNotAvailableError


class LocalLLM:
    """
    Async wrapper for Ollama local inference.
    Important: call unload() before WriterAgent's parallel API calls on 8GB systems.
    """

    def __init__(self, config: dict):
        llm_cfg = config.get("llm", {})
        self._model = llm_cfg.get("local_model", "phi4-mini")
        self._host = llm_cfg.get("ollama_host", "http://localhost:11434")
        self._threads = llm_cfg.get("local_model_threads", 4)

    async def generate(
        self, prompt: str, max_tokens: int = 500, agent: str = "unknown"
    ) -> str:
        """Run inference on the local model."""
        # TODO(Commit 3): Full implementation
        #   POST /api/generate, stream=False, options={num_predict, temperature, num_thread}
        #   log_local_call() after response
        raise NotImplementedError("LocalLLM.generate() not yet implemented — see Commit 3")

    async def unload(self) -> None:
        """
        Free model memory before writer agent's parallel API calls.
        Frees ~3.5GB on 8GB systems. Called by orchestrator before WriterAgent.
        """
        # TODO(Commit 3): POST /api/generate with keep_alive=0
        pass

    async def reload(self) -> None:
        """Warm up model after writer agent completes."""
        # TODO(Commit 3): Send a short test prompt to load model back into memory
        pass

    async def is_available(self) -> bool:
        """Check if Ollama server is running (used by health check and --no-local-model)."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{self._host}/api/tags")
                return r.status_code == 200
        except Exception:
            return False
