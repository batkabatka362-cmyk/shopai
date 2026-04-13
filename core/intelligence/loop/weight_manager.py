"""Weight management — persistent learned weights for the intelligence loop."""
from __future__ import annotations

from utils.logger import get_logger

logger = get_logger("intelligence_loop.weight_manager")

# Persistent learned weights — saved to disk, survives restarts
try:
    from core.memory.storage_config import learned_weights_path
    _WEIGHTS_PATH = learned_weights_path()
except Exception:
    _WEIGHTS_PATH = "/tmp/shopai_learned_weights.json"
_learned_weights: dict[str, float] = {}
_weights_loaded = False


def _load_weights() -> None:
    """Load learned weights from disk on first access."""
    global _learned_weights, _weights_loaded
    if _weights_loaded:
        return
    _weights_loaded = True
    try:
        import json
        import os
        if os.path.exists(_WEIGHTS_PATH):
            with open(_WEIGHTS_PATH) as f:
                data = json.load(f)
                if isinstance(data, dict):
                    _learned_weights.update(data)
                    logger.info("Loaded %d learned weights from disk", len(data))
    except Exception as exc:
        logger.warning("Failed to load learned weights: %s", exc)


def _save_weights() -> None:
    """Save learned weights to disk (atomic write)."""
    try:
        import json
        import os
        tmp = _WEIGHTS_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(_learned_weights, f)
        os.replace(tmp, _WEIGHTS_PATH)
    except Exception as exc:
        logger.warning("Failed to save learned weights: %s", exc)


def get_learned_weights() -> dict[str, float]:
    """Get current learned scoring weight adjustments."""
    _load_weights()
    return dict(_learned_weights)
