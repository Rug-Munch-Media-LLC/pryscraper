"""Pry Config — runtime configuration for proxy, Tor, VPN, and anti-detection.
Users can configure at startup (env vars) or at runtime (API calls)."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

import json
import os

CONFIG_FILE = "/app/config.json"
DEFAULT_CONFIG = {
    "proxy": {"enabled": False, "type": "", "url": "", "username": "", "password": ""},
    "tor": {"enabled": False, "socks5_host": "tor", "socks5_port": 9050, "control_port": 9051},
    "rotation": {
        "user_agent": "rotate",
        "ip": "off",
        "timing": "random",
        "delay_range": [0.5, 3.0],
    },
    "stealth": {
        "webdriver_override": True,
        "canvas_noise": True,
        "webrtc_disable": True,
        "geolocation_spoof": True,
    },
    "retry": {"max_attempts": 3, "min_quality": 20, "backoff": "exponential"},
    "output": {"default_format": "markdown", "max_chars": 100000, "include_links": True},
    "rate_limit": {"rpm": 120, "burst": 200},
}


class PryConfig:
    """Configuration manager — loads from env vars, config file, and API overrides."""

    def __init__(self):
        self.config = json.loads(json.dumps(DEFAULT_CONFIG))  # Deep copy
        self._load_env()
        self._load_file()
        self._resolve_proxy_chain()

    def _load_env(self):
        """Environment variables override defaults."""
        if os.getenv("TOR_ENABLED", "").lower() in ("1", "true", "yes"):
            self.config["tor"]["enabled"] = True
        if os.getenv("TOR_SOCKS5_HOST"):
            self.config["tor"]["socks5_host"] = os.getenv("TOR_SOCKS5_HOST")
        if os.getenv("TOR_SOCKS5_PORT"):
            self.config["tor"]["socks5_port"] = int(os.getenv("TOR_SOCKS5_PORT"))
        if os.getenv("PROXY_URL"):
            self.config["proxy"]["enabled"] = True
            self.config["proxy"]["url"] = os.getenv("PROXY_URL")
            self.config["proxy"]["type"] = os.getenv("PROXY_TYPE", "http")
        if os.getenv("PROXY_USERNAME"):
            self.config["proxy"]["username"] = os.getenv("PROXY_USERNAME")
        if os.getenv("PROXY_PASSWORD"):
            self.config["proxy"]["password"] = os.getenv("PROXY_PASSWORD")
        if os.getenv("IP_ROTATION"):
            self.config["rotation"]["ip"] = os.getenv("IP_ROTATION")
        if os.getenv("MAX_RETRIES"):
            self.config["retry"]["max_attempts"] = int(os.getenv("MAX_RETRIES"))
        if os.getenv("MIN_QUALITY"):
            self.config["retry"]["min_quality"] = int(os.getenv("MIN_QUALITY"))
        if os.getenv("RATE_LIMIT_RPM"):
            self.config["rate_limit"]["rpm"] = int(os.getenv("RATE_LIMIT_RPM"))

    def _load_file(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE) as f:
                    user_config = json.load(f)
                self._deep_merge(self.config, user_config)
            except OSError:
                pass

    def _deep_merge(self, base: dict, override: dict):
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value

    def _resolve_proxy_chain(self):
        """Build the proxy chain: Tor -> User Proxy -> Direct"""
        proxies = []
        if self.config["tor"]["enabled"]:
            proxies.append(
                f"socks5://{self.config['tor']['socks5_host']}:{self.config['tor']['socks5_port']}"
            )
        if self.config["proxy"]["enabled"]:
            url = self.config["proxy"]["url"]
            if self.config["proxy"]["username"]:
                netloc = url.split("://")[1] if "://" in url else url
                proxies.append(
                    f"{self.config['proxy']['type']}://{self.config['proxy']['username']}:{self.config['proxy']['password']}@{netloc}"
                )
            else:
                proxies.append(url)
        self.config["_proxy_chain"] = proxies
        self.config["_proxy_url"] = proxies[0] if proxies else None

    def get_proxy_url(self) -> str | None:
        return self.config.get("_proxy_url")

    def get_proxy_chain(self) -> list:
        return self.config.get("_proxy_chain", [])

    def get(self, key: str, default=None):
        keys = key.split(".")
        val = self.config
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k)
            else:
                return default
            if val is None:
                return default
        return val if val is not None else default

    def to_dict(self) -> dict:
        return {k: v for k, v in self.config.items() if not k.startswith("_")}

    def update(self, updates: dict) -> dict:
        self._deep_merge(self.config, updates)
        self._resolve_proxy_chain()
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.to_dict(), f, indent=2)
        except OSError:
            pass
        return {"status": "ok", "config": self.to_dict()}


