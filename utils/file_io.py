"""
Atomic JSON file I/O with backup and GDPR audit logging.
Rule: never write application_tracker.json directly — always use atomic_write_json().
"""
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Union

from utils.exceptions import FileIOError
from utils.logger import audit


def read_json(
    filepath: Union[str, Path],
    agent: str = "system",
) -> Dict[str, Any]:
    """Read and parse a JSON file. Raises FileIOError if missing or malformed."""
    path = Path(filepath)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        audit("read", agent, path.stem, "success")
        return data
    except FileNotFoundError:
        raise FileIOError(f"File not found: {path}", agent=agent)
    except json.JSONDecodeError as exc:
        raise FileIOError(f"Malformed JSON in {path}: {exc}", agent=agent)
    except OSError as exc:
        raise FileIOError(f"Cannot read {path}: {exc}", agent=agent)


def write_json(
    filepath: Union[str, Path],
    data: dict,
    agent: str = "system",
) -> None:
    """Non-atomic write for non-critical files (job_matches, fix_instructions, etc.)."""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        audit("write", agent, path.stem, "success")
    except (OSError, TypeError) as exc:
        audit("write", agent, path.stem, "failure", detail=str(exc))
        raise FileIOError(f"Failed to write {path}: {exc}", agent=agent)


def atomic_write_json(
    filepath: Union[str, Path],
    data: dict,
    agent: str = "tracker",
) -> None:
    """
    Write JSON atomically: backup → temp write → validate → os.replace().
    The only safe way to write application_tracker.json.

    If validation fails the temp file is deleted and the original is untouched.
    """
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = path.with_suffix("").with_suffix(".backup.json")

    # Backup existing file before touching anything
    if path.exists():
        shutil.copy2(path, backup_path)

    # Write to a temp file in the same directory (os.replace requires same filesystem)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp.json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        # Validate by reading back — catches serialization bugs
        with open(tmp_path, encoding="utf-8") as f:
            json.load(f)

        os.replace(tmp_path, path)
        audit("write", agent, path.stem, "success")

    except Exception as exc:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        audit("write", agent, path.stem, "failure", detail=str(exc))
        raise FileIOError(
            f"Atomic write failed for {path}: {exc}",
            agent=agent,
            context={"backup_exists": backup_path.exists()},
        )


def restore_from_backup(
    filepath: Union[str, Path],
    agent: str = "tracker",
) -> bool:
    """
    Restore a JSON file from its .backup.json counterpart.
    Returns True if successful, False if no backup exists.
    """
    path = Path(filepath)
    backup = path.with_suffix("").with_suffix(".backup.json")
    if not backup.exists():
        return False
    try:
        shutil.copy2(backup, path)
        audit("restore", agent, path.stem, "success")
        return True
    except OSError as exc:
        audit("restore", agent, path.stem, "failure", detail=str(exc))
        return False


def read_text(
    filepath: Union[str, Path],
    agent: str = "system",
) -> str:
    """Read a plain-text file (prompts, markdown). Raises FileIOError if missing."""
    path = Path(filepath)
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileIOError(f"File not found: {path}", agent=agent)
    except OSError as exc:
        raise FileIOError(f"Failed to read {path}: {exc}", agent=agent)
