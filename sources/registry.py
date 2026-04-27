"""
Job source registry — discovers, validates, and manages active job sources.
Sources are auto-discovered from the sources/ package: no manual registration required.
Add/remove sources at runtime via enable_source() / disable_source().
"""
import importlib
import pkgutil
from pathlib import Path
from typing import Dict, List, Optional, Type

from sources.base_source import BaseJobSource
from utils.exceptions import ConfigError
from utils.logger import run_log


def _discover_source_classes() -> Dict[str, Type[BaseJobSource]]:
    """Scan the sources/ package and collect all BaseJobSource subclasses."""
    discovered: Dict[str, Type[BaseJobSource]] = {}
    sources_dir = Path(__file__).parent

    for _, module_name, _ in pkgutil.iter_modules([str(sources_dir)]):
        if module_name in ("base_source", "registry"):
            continue
        try:
            module = importlib.import_module(f"sources.{module_name}")
            for attr_name in dir(module):
                obj = getattr(module, attr_name)
                if (
                    isinstance(obj, type)
                    and issubclass(obj, BaseJobSource)
                    and obj is not BaseJobSource
                    and hasattr(obj, "source_id")
                ):
                    discovered[obj.source_id] = obj
        except ImportError as exc:
            run_log("WARNING", "registry", f"Could not load source module '{module_name}': {exc}")

    return discovered


class SourceRegistry:
    """
    Manages active job sources for the scout agent.
    Initialized from config.json; supports runtime enable/disable.
    """

    def __init__(self, config: Dict):
        self._sources_config: Dict = config.get("job_sources", {})
        self._all_classes: Dict[str, Type[BaseJobSource]] = _discover_source_classes()
        self._active: Dict[str, BaseJobSource] = {}
        self._load_active_from_config()

    def _load_active_from_config(self) -> None:
        sources_cfg = self._sources_config.get("sources", {})
        active_ids = self._sources_config.get("active_sources", [])

        for source_id in active_ids:
            if source_id not in self._all_classes:
                run_log("WARNING", "registry", f"Source '{source_id}' listed as active but no implementation found")
                continue
            source_cfg = sources_cfg.get(source_id, {})
            if not source_cfg.get("enabled", True):
                run_log("INFO", "registry", f"Source '{source_id}' is disabled in config — skipping")
                continue

            instance = self._all_classes[source_id]()
            error = instance.validate_config(source_cfg)
            if error:
                run_log("WARNING", "registry", f"Source '{source_id}' config invalid: {error} — skipping")
                continue

            self._active[source_id] = instance
            run_log("INFO", "registry", f"Activated job source: {instance.source_name}")

        if not self._active:
            run_log("WARNING", "registry", "No active job sources configured. Check config.json job_sources.active_sources")

    # ── Public interface ──────────────────────────────────────────────────────

    @property
    def active_sources(self) -> List[BaseJobSource]:
        return list(self._active.values())

    def get_source(self, source_id: str) -> Optional[BaseJobSource]:
        return self._active.get(source_id)

    def list_all(self) -> Dict[str, bool]:
        """Returns all discovered source IDs with their active status."""
        return {sid: sid in self._active for sid in self._all_classes}

    def enable_source(self, source_id: str, source_config: Dict) -> None:
        """Dynamically enable a source (used by CLI or dashboard)."""
        if source_id not in self._all_classes:
            raise ConfigError(f"Unknown source: '{source_id}'. Available: {list(self._all_classes)}")
        instance = self._all_classes[source_id]()
        error = instance.validate_config(source_config)
        if error:
            raise ConfigError(f"Source '{source_id}' config invalid: {error}")
        self._active[source_id] = instance
        run_log("INFO", "registry", f"Dynamically enabled: {instance.source_name}")

    def disable_source(self, source_id: str) -> None:
        """Dynamically disable a source."""
        if source_id in self._active:
            name = self._active.pop(source_id).source_name
            run_log("INFO", "registry", f"Disabled source: {name}")
