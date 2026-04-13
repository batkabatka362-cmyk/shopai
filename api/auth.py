"""API Authentication — simple token-based auth for dashboard API."""
from __future__ import annotations
import hashlib
import os
import time
from typing import Any
from utils.logger import get_logger
logger = get_logger("api.auth")


class APIAuth:
    """Simple token-based API authentication."""

    def __init__(self):
        self._tokens: dict[str, dict] = {}
        self._master_token = os.environ.get("SHOPAI_API_TOKEN", "")
        if not self._master_token:
            # Generate default token
            self._master_token = hashlib.sha256(
                "shopai_{}".format(int(time.time())).encode()
            ).hexdigest()[:32]

    def validate(self, token: str) -> bool:
        if not self._master_token:
            return True  # No auth configured
        if token == self._master_token:
            return True
        return token in self._tokens

    def create_token(self, name: str, expires_hours: int = 24) -> str:
        token = hashlib.sha256(
            "{}_{}".format(name, time.time()).encode()
        ).hexdigest()[:32]
        self._tokens[token] = {
            "name": name,
            "created": time.time(),
            "expires": time.time() + expires_hours * 3600,
        }
        return token

    def get_master_token(self) -> str:
        return self._master_token

    def get_stats(self) -> dict:
        return {
            "active_tokens": len(self._tokens),
            "has_master": bool(self._master_token),
        }


_instance = None
def get_api_auth():
    global _instance
    if _instance is None:
        _instance = APIAuth()
    return _instance
