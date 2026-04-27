"""
Ollama server lifecycle management.
Starts the server if not running, pulls the model on first run,
and provides health checks used by the orchestrator.
"""
import json
import subprocess
import time

import httpx

from utils.exceptions import OllamaNotAvailableError
from utils.logger import run_log

_OLLAMA_URL = "http://localhost:11434"
_DEFAULT_MODEL = "phi4-mini"
_START_TIMEOUT = 15  # seconds to wait for server to come up


def ensure_ollama_running(model: str = _DEFAULT_MODEL, host: str = _OLLAMA_URL) -> None:
    """
    Ensure Ollama is running and the model is downloaded.
    Starts the server process if needed, pulls model with progress on first run.
    Called once at the start of each run when use_local_model=True.
    """
    if not is_server_running(host):
        _start_server(host)

    if not is_model_available(model, host):
        run_log("INFO", "ollama_manager", f"Model '{model}' not found — pulling (~2.3GB, may take several minutes)")
        _pull_model_with_progress(model, host)
        run_log("INFO", "ollama_manager", f"Model '{model}' ready")
    else:
        run_log("INFO", "ollama_manager", f"Ollama running, model '{model}' available")


def _start_server(host: str) -> None:
    """Launch 'ollama serve' as a background process and wait for it to respond."""
    run_log("INFO", "ollama_manager", "Ollama not running — attempting to start...")
    try:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        raise OllamaNotAvailableError(
            "Ollama is not installed. Install from https://ollama.ai then re-run."
        )

    for _ in range(_START_TIMEOUT):
        time.sleep(1)
        if is_server_running(host):
            run_log("INFO", "ollama_manager", "Ollama server started successfully")
            return

    raise OllamaNotAvailableError(
        f"Ollama did not respond within {_START_TIMEOUT}s of starting."
    )


def _pull_model_with_progress(model: str, host: str) -> None:
    """
    Stream the model pull with a progress bar printed to stdout.
    Resolves I-005: first-run progress indicator for large downloads.
    """
    try:
        with httpx.Client(timeout=None) as client:
            with client.stream("POST", f"{host}/api/pull", json={"name": model}) as r:
                r.raise_for_status()
                last_pct = -1
                for line in r.iter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    total = data.get("total", 0)
                    completed = data.get("completed", 0)
                    status = data.get("status", "")

                    if total and completed:
                        pct = int(completed / total * 100)
                        if pct != last_pct and pct % 5 == 0:
                            mb_done = completed // 1_048_576
                            mb_total = total // 1_048_576
                            print(
                                f"\r  Pulling {model}: {pct}% ({mb_done}MB / {mb_total}MB)   ",
                                end="",
                                flush=True,
                            )
                            last_pct = pct
                    elif status:
                        print(f"\r  {status}...                    ", end="", flush=True)

        print()  # newline after progress bar

    except httpx.HTTPStatusError as exc:
        raise OllamaNotAvailableError(
            f"Failed to pull model '{model}': HTTP {exc.response.status_code}"
        )
    except Exception as exc:
        raise OllamaNotAvailableError(f"Failed to pull model '{model}': {exc}")


def is_model_available(model: str = _DEFAULT_MODEL, host: str = _OLLAMA_URL) -> bool:
    """Return True if the model is already downloaded locally."""
    try:
        r = httpx.get(f"{host}/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models", [])]
        return any(model in m for m in models)
    except Exception:
        return False


def is_server_running(host: str = _OLLAMA_URL) -> bool:
    """Return True if Ollama server is up and responding."""
    try:
        r = httpx.get(f"{host}/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False
