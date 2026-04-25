"""
Ollama server lifecycle management.
Starts the server if not running, pulls the model on first run,
and provides health checks used by the orchestrator.

Full implementation: Commit 3
See ISSUES.md I-005 for the first-run progress indicator requirement.
"""
import subprocess
import time
from typing import Optional

import httpx

from utils.logger import run_log
from utils.exceptions import OllamaNotAvailableError

_OLLAMA_URL = "http://localhost:11434"
_DEFAULT_MODEL = "phi4-mini"


def ensure_ollama_running(model: str = _DEFAULT_MODEL, host: str = _OLLAMA_URL) -> None:
    """
    Start Ollama if not already running. Pull the model if not yet downloaded.
    Called once at the start of each run (when use_local_model=True).

    TODO(Commit 3, I-005): Add progress indicator for model pull (~2.3GB download).
    """
    # TODO(Commit 3): Full implementation
    raise NotImplementedError("ollama_manager not yet implemented — see Commit 3")


def is_model_available(model: str = _DEFAULT_MODEL, host: str = _OLLAMA_URL) -> bool:
    """Check if a specific model is already downloaded."""
    try:
        r = httpx.get(f"{host}/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models", [])]
        return any(model in m for m in models)
    except Exception:
        return False


def is_server_running(host: str = _OLLAMA_URL) -> bool:
    """Check if the Ollama server is running and responding."""
    try:
        r = httpx.get(f"{host}/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False
