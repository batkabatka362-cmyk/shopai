"""Prompt Manager -- versioned prompt template management with persistence."""
from __future__ import annotations

import json
import logging
import os
import string
import time
from typing import Any

logger = logging.getLogger(__name__)

_PERSIST_PATH = "/tmp/shopai_prompts.json"


class PromptManager:
    """Manages prompt templates keyed by (engine_name, step) with versioning."""

    def __init__(self, persist_path: str = _PERSIST_PATH) -> None:
        self._persist_path = persist_path
        # _prompts maps "engine_name:step" -> {
        #     "engine_name": str,
        #     "step": str,
        #     "template": str,           # latest template
        #     "current_version": int,
        #     "versions": {int: {"template": str, "created_at": float}}
        # }
        self._prompts: dict[str, dict[str, Any]] = {}
        self._load()

    # ---- Key helper ----------------------------------------------------

    @staticmethod
    def _key(engine_name: str, step: str) -> str:
        return f"{engine_name}:{step}"

    # ---- Public API ----------------------------------------------------

    def register_prompt(
        self,
        engine_name: str,
        step: str,
        template: str,
        version: int = 1,
    ) -> None:
        key = self._key(engine_name, step)
        if key in self._prompts:
            raise ValueError(
                f"Prompt '{key}' already registered. Use update_prompt to create a new version."
            )
        self._prompts[key] = {
            "engine_name": engine_name,
            "step": step,
            "template": template,
            "current_version": version,
            "versions": {
                version: {"template": template, "created_at": time.time()}
            },
        }
        self._persist()

    def get_prompt(
        self,
        engine_name: str,
        step: str,
        version: int | None = None,
    ) -> str:
        key = self._key(engine_name, step)
        entry = self._prompts.get(key)
        if entry is None:
            raise KeyError(f"Prompt '{key}' not found")
        if version is None:
            return entry["template"]
        ver = entry["versions"].get(version) or entry["versions"].get(str(version))
        if ver is None:
            raise KeyError(f"Version {version} not found for prompt '{key}'")
        return ver["template"]

    def render_prompt(
        self,
        engine_name: str,
        step: str,
        context: dict,
        version: int | None = None,
    ) -> str:
        template = self.get_prompt(engine_name, step, version)
        try:
            return string.Template(template).safe_substitute(context)
        except Exception:
            # Fallback to str.format style
            try:
                return template.format(**context)
            except (KeyError, IndexError):
                return template

    def list_prompts(self, engine_name: str | None = None) -> list[dict]:
        results: list[dict] = []
        for entry in self._prompts.values():
            if engine_name is not None and entry["engine_name"] != engine_name:
                continue
            results.append({
                "engine_name": entry["engine_name"],
                "step": entry["step"],
                "current_version": entry["current_version"],
                "versions": sorted(
                    int(v) if isinstance(v, str) else v
                    for v in entry["versions"]
                ),
            })
        return results

    def update_prompt(self, engine_name: str, step: str, template: str) -> int:
        key = self._key(engine_name, step)
        entry = self._prompts.get(key)
        if entry is None:
            raise KeyError(f"Prompt '{key}' not found")
        new_version = entry["current_version"] + 1
        entry["versions"][new_version] = {
            "template": template,
            "created_at": time.time(),
        }
        entry["current_version"] = new_version
        entry["template"] = template
        self._persist()
        return new_version

    def delete_prompt(
        self,
        engine_name: str,
        step: str,
        version: int | None = None,
    ) -> bool:
        key = self._key(engine_name, step)
        entry = self._prompts.get(key)
        if entry is None:
            return False
        if version is None:
            del self._prompts[key]
            self._persist()
            return True
        v_key: Any = version
        if v_key not in entry["versions"]:
            v_key = str(version)
        if v_key not in entry["versions"]:
            return False
        del entry["versions"][v_key]
        # If we deleted the current version, roll back
        if entry["current_version"] == version:
            if entry["versions"]:
                latest = max(
                    int(v) if isinstance(v, str) else v
                    for v in entry["versions"]
                )
                entry["current_version"] = latest
                entry["template"] = entry["versions"][latest]["template"]
            else:
                del self._prompts[key]
        self._persist()
        return True

    # ---- Persistence ---------------------------------------------------

    def _persist(self) -> None:
        # Convert int keys to strings for JSON
        serializable: dict[str, Any] = {}
        for key, entry in self._prompts.items():
            e = dict(entry)
            e["versions"] = {str(k): v for k, v in entry["versions"].items()}
            serializable[key] = e
        try:
            with open(self._persist_path, "w") as f:
                json.dump(serializable, f, indent=2)
        except OSError as exc:
            logger.warning(
                "PromptManager._persist failed (%s): %s",
                self._persist_path, exc,
            )

    def _load(self) -> None:
        if not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path) as f:
                data = json.load(f)
            for key, entry in data.items():
                # Restore int keys
                versions: dict[int, Any] = {}
                for vk, vv in entry.get("versions", {}).items():
                    versions[int(vk)] = vv
                entry["versions"] = versions
                entry["current_version"] = int(entry.get("current_version", 1))
                self._prompts[key] = entry
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.warning(
                "PromptManager._load failed (%s): %s",
                self._persist_path, exc,
            )
