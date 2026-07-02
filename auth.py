# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Pry — Authentication with JWT and API keys, per-key rate limiting."""

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# Try to import JWT library
try:
    import jwt
    _has_jwt = True
except ImportError:
    _has_jwt = False

# Configuration
# JWT secret: prefer gopass (PRY_SECRET_BACKEND=gopass), fall back to env, then to a
# random ephemeral default. The default is intentionally NOT a fixed string so that
# an unset JWT_SECRET cannot accidentally sign tokens in a way that survives restart.
try:
    from secrets_backend import get_secret
    JWT_SECRET = get_secret("jwt_secret") or os.getenv("PRY_JWT_SECRET") or (
        "ephemeral-" + secrets.token_hex(32)
    )
except ImportError:
    JWT_SECRET = os.getenv("PRY_JWT_SECRET") or ("ephemeral-" + secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24
API_KEY_LENGTH = 32
DEFAULT_RATE_LIMIT_RPM = 60


class AuthManager:
    """Manage users, API keys, and rate limiting."""

    def __init__(self, storage: Any = None):
        self._storage = storage  # Will be set when DB is ready
        self._rate_limits: dict[str, dict[str, Any]] = {}
        self._users: dict[str, dict[str, Any]] = {}
        self._api_keys: dict[str, dict[str, Any]] = {}

    def hash_password(self, password: str, salt: str | None = None) -> tuple[str, str]:
        if salt is None: salt = secrets.token_hex(16)
        h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
        return h.hex(), salt

    def verify_password(self, password: str, hashed: str, salt: str) -> bool:
        h, _ = self.hash_password(password, salt)
        return hmac.compare_digest(h, hashed)

    def create_user(self, email: str, password: str, role: str = "user") -> dict[str, Any]:
        user_id = secrets.token_hex(12)
        pwd_hash, salt = self.hash_password(password)
        user = {
            "id": user_id, "email": email, "password_hash": pwd_hash, "salt": salt,
            "role": role, "created_at": datetime.now(UTC).isoformat(),
            "active": True, "api_keys": [],
        }
        self._users[user_id] = user
        return user

    def create_api_key(self, user_id: str, name: str = "default", rate_limit_rpm: int = DEFAULT_RATE_LIMIT_RPM) -> str:
        key = "pry_" + secrets.token_urlsafe(API_KEY_LENGTH)
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        api_key = {
            "key_hash": key_hash, "user_id": user_id, "name": name,
            "rate_limit_rpm": rate_limit_rpm,
            "created_at": datetime.now(UTC).isoformat(),
            "last_used": None, "use_count": 0,
        }
        self._api_keys[key_hash] = api_key
        if user_id in self._users:
            self._users[user_id]["api_keys"].append(key_hash)
        return key

    def verify_api_key(self, key: str) -> dict[str, Any] | None:
        if not key or not key.startswith("pry_"):
            return None
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        api_key = self._api_keys.get(key_hash)
        if api_key:
            api_key["last_used"] = datetime.now(UTC).isoformat()
            api_key["use_count"] = api_key.get("use_count", 0) + 1
        return api_key

    def check_rate_limit(self, api_key: str) -> tuple[bool, int]:
        if not api_key: return True, 0
        now = time.time()
        rl = self._rate_limits.setdefault(api_key, {"window_start": now, "count": 0})
        if now - rl["window_start"] > 60:
            rl["window_start"] = now
            rl["count"] = 0
        rl["count"] += 1
        api_key_data = self.verify_api_key(api_key)
        limit = api_key_data.get("rate_limit_rpm", DEFAULT_RATE_LIMIT_RPM) if api_key_data else DEFAULT_RATE_LIMIT_RPM
        remaining = max(0, limit - rl["count"])
        return rl["count"] <= limit, remaining

    def create_jwt(self, user_id: str, role: str = "user") -> str:
        if not _has_jwt:
            # Fallback: simple base64 token (NOT for production)
            payload = {"sub": user_id, "role": role, "exp": time.time() + JWT_EXPIRY_HOURS * 3600}
            return "pry_jwt." + base64_encode(json.dumps(payload))
        payload = {"sub": user_id, "role": role, "exp": datetime.now(UTC) + timedelta(hours=JWT_EXPIRY_HOURS)}
        return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

    def verify_jwt(self, token: str) -> dict[str, Any] | None:
        if not _has_jwt:
            try:
                if not token.startswith("pry_jwt."): return None
                payload = json.loads(base64_decode(token[8:]))
                if payload.get("exp", 0) < time.time(): return None
                return payload
            except Exception:
                return None
        try:
            return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        except Exception:
            return None


def base64_encode(s: str) -> str:
    import base64
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def base64_decode(s: str) -> str:
    import base64
    padding = 4 - len(s) % 4
    if padding != 4: s += "=" * padding
    return base64.urlsafe_b64decode(s.encode()).decode()
