"""Pry — Multi-provider CAPTCHA solver with auto-fallback.
Supports: Capsolver -> 2Captcha -> Anti-Captcha -> CapMonster -> DeathByCaptcha -> NextCaptcha
Also handles Turnstile, reCAPTCHA v2/v3/invisible, and hCaptcha."""

# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).

import asyncio
import json
import logging
import time
from typing import Any, ClassVar

logger = logging.getLogger(__name__)


class CaptchaSolver:
    """Unified CAPTCHA solver with 6+ providers and automatic fallback chain."""

    PROVIDER_PRIORITY: ClassVar[list[str]] = [
        "capsolver",
        "2captcha",
        "anti_captcha",
        "capmonster",
        "deathbycaptcha",
        "nextcaptcha",
    ]

    def __init__(self, api_keys: dict[str, str] | None = None):
        self.api_keys = api_keys or {}
        self.provider_stats: dict[str, dict[str, Any]] = {
            p: {"success": 0, "failed": 0, "avg_time": 0, "last_error": ""}
            for p in self.PROVIDER_PRIORITY
        }

    async def solve_recaptcha_v2(
        self, site_key: str, page_url: str, provider: str = ""
    ) -> dict[str, Any]:
        """Solve reCAPTCHA v2."""
        providers = [provider] if provider else self.PROVIDER_PRIORITY
        for prov in providers:
            key = self.api_keys.get(prov) or self.api_keys.get(prov + "_api_key", "")
            if not key:
                continue
            try:
                start = time.time()
                result = await self._solve_with(prov, "ReCaptchaV2Task", site_key, page_url, key)
                elapsed = time.time() - start
                self._record(prov, True, elapsed)
                return {
                    "success": True,
                    "provider": prov,
                    "token": result,
                    "elapsed": round(elapsed, 2),
                }
            except Exception as e:  # noqa: BLE001
                self._record(prov, False, 0, str(e))
                logger.warning(
                    "captcha_provider_failed", extra={"provider": prov, "error": str(e)[:80]}
                )
        return {"success": False, "error": "All CAPTCHA providers failed"}

    async def solve_recaptcha_v3(
        self, site_key: str, page_url: str, action: str = "verify", min_score: float = 0.3
    ) -> dict[str, Any]:
        """Solve reCAPTCHA v3 (invisible, returns score)."""
        for prov in self.PROVIDER_PRIORITY:
            key = self.api_keys.get(prov) or self.api_keys.get(prov + "_api_key", "")
            if not key:
                continue
            try:
                result = await self._solve_with(
                    prov,
                    "ReCaptchaV3Task",
                    site_key,
                    page_url,
                    key,
                    extra={"action": action, "minScore": min_score},
                )
                return {"success": True, "provider": prov, "token": result}
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "recaptcha_v3_failed", extra={"provider": prov, "error": str(e)[:80]}
                )
        return {"success": False, "error": "All reCAPTCHA v3 providers failed"}

    async def solve_turnstile(self, site_key: str, page_url: str) -> dict[str, Any]:
        """Solve Cloudflare Turnstile challenge."""
        for prov in self.PROVIDER_PRIORITY:
            key = self.api_keys.get(prov) or self.api_keys.get(prov + "_api_key", "")
            if not key:
                continue
            try:
                result = await self._solve_with(prov, "TurnstileTask", site_key, page_url, key)
                return {"success": True, "provider": prov, "token": result}
            except Exception as e:  # noqa: BLE001
                logger.warning("turnstile_failed", extra={"provider": prov, "error": str(e)[:80]})
        return {"success": False, "error": "All Turnstile providers failed"}

    async def solve_hcaptcha(self, site_key: str, page_url: str) -> dict[str, Any]:
        """Solve hCaptcha."""
        for prov in self.PROVIDER_PRIORITY:
            key = self.api_keys.get(prov) or self.api_keys.get(prov + "_api_key", "")
            if not key:
                continue
            try:
                result = await self._solve_with(prov, "HCaptchaTask", site_key, page_url, key)
                return {"success": True, "provider": prov, "token": result}
            except Exception as e:  # noqa: BLE001
                logger.warning("hcaptcha_failed", extra={"provider": prov, "error": str(e)[:80]})
        return {"success": False, "error": "All hCaptcha providers failed"}

    async def solve_image(self, image_base64: str, case_sensitive: bool = False) -> dict[str, Any]:
        """Solve image-based CAPTCHA (text from image)."""
        for prov in self.PROVIDER_PRIORITY:
            key = self.api_keys.get(prov) or self.api_keys.get(prov + "_api_key", "")
            if not key:
                continue
            try:
                result = await self._solve_image_with(prov, image_base64, key, case_sensitive)
                return {"success": True, "provider": prov, "text": result}
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "image_captcha_failed", extra={"provider": prov, "error": str(e)[:80]}
                )
        return {"success": False, "error": "All image CAPTCHA providers failed"}

    async def _solve_with(
        self,
        provider: str,
        task_type: str,
        site_key: str,
        page_url: str,
        api_key: str,
        extra: dict | None = None,
    ) -> str:
        if provider == "capsolver":
            return await self._capsolver(task_type, site_key, page_url, api_key, extra)
        elif provider == "2captcha":
            return await self._two_captcha(task_type, site_key, page_url, api_key, extra)
        elif provider == "anti_captcha":
            return await self._anti_captcha(task_type, site_key, page_url, api_key, extra)
        elif provider == "capmonster":
            return await self._capmonster(task_type, site_key, page_url, api_key, extra)
        elif provider == "deathbycaptcha":
            return await self._deathbycaptcha(task_type, site_key, page_url, api_key, extra)
        elif provider == "nextcaptcha":
            return await self._nextcaptcha(task_type, site_key, page_url, api_key, extra)
        raise ValueError(f"Unknown provider: {provider}")

    async def _capsolver(
        self, task_type: str, site_key: str, page_url: str, api_key: str, extra: dict | None = None
    ) -> str:
        from client import get_client

        client = await get_client()
        task: dict[str, Any] = {"type": task_type, "websiteKey": site_key, "websiteURL": page_url}
        if extra:
            task.update(extra)
        resp = await client.post(
            "https://api.capsolver.com/createTask",
            json={"clientKey": api_key, "task": task},
            timeout=30,
        )
        data = resp.json()
        task_id = data.get("taskId")
        if not task_id:
            raise Exception(data.get("errorDescription", "Capsolver error"))
        for _ in range(60):
            await asyncio.sleep(2)
            r = await client.post(
                "https://api.capsolver.com/getTaskResult",
                json={"clientKey": api_key, "taskId": task_id},
            )
            rd = r.json()
            if rd.get("status") == "ready":
                return rd["solution"].get("gRecaptchaResponse") or rd["solution"].get("token", "")
            if rd.get("status") == "failed":
                raise Exception("Capsolver failed")
        raise Exception("Capsolver timed out")

    async def _two_captcha(
        self, task_type: str, site_key: str, page_url: str, api_key: str, extra: dict | None = None
    ) -> str:
        from client import get_client

        client = await get_client()
        method = {
            "ReCaptchaV2Task": "userrecaptcha",
            "ReCaptchaV3Task": "recaptcha_v3",
            "HCaptchaTask": "hcaptcha",
            "TurnstileTask": "turnstile",
        }.get(task_type, "userrecaptcha")
        params: dict[str, Any] = {
            "key": api_key,
            "method": method,
            "googlekey": site_key,
            "pageurl": page_url,
            "json": 1,
        }
        if extra:
            params.update(extra)
        resp = await client.post("https://2captcha.com/in.php", data=params, timeout=30)
        data = resp.json()
        if data.get("status") != 1:
            raise Exception(data.get("request", "2captcha error"))
        request_id = data["request"]
        for _ in range(60):
            await asyncio.sleep(3)
            r = await client.get(
                f"https://2captcha.com/res.php?key={api_key}&action=get&id={request_id}&json=1"
            )
            rd = r.json()
            if rd.get("status") == 1:
                return rd["request"]
            if rd.get("request") and "CAPCHA_NOT_READY" not in str(rd["request"]):
                raise Exception(f"2captcha: {rd['request']}")
        raise Exception("2captcha timed out")

    async def _anti_captcha(
        self, task_type: str, site_key: str, page_url: str, api_key: str, extra: dict | None = None
    ) -> str:
        from client import get_client

        client = await get_client()
        type_map = {
            "ReCaptchaV2Task": "NoCaptchaTaskProxyless",
            "ReCaptchaV3Task": "RecaptchaV3TaskProxyless",
            "HCaptchaTask": "HCaptchaTaskProxyless",
            "TurnstileTask": "TurnstileTaskProxyless",
        }
        task = {
            "type": type_map.get(task_type, "NoCaptchaTaskProxyless"),
            "websiteURL": page_url,
            "websiteKey": site_key,
        }
        if extra:
            task.update(extra)
        resp = await client.post(
            "https://api.anti-captcha.com/createTask",
            json={"clientKey": api_key, "task": task},
            timeout=30,
        )
        data = resp.json()
        if data.get("errorId") != 0:
            raise Exception(data.get("errorDescription", "Anti-Captcha error"))
        task_id = data["taskId"]
        for _ in range(60):
            await asyncio.sleep(2)
            r = await client.post(
                "https://api.anti-captcha.com/getTaskResult",
                json={"clientKey": api_key, "taskId": task_id},
            )
            rd = r.json()
            if rd.get("status") == "ready":
                return rd["solution"].get("gRecaptchaResponse", "")
            if rd.get("errorId") != 0:
                raise Exception(rd.get("errorDescription", ""))
        raise Exception("Anti-Captcha timed out")

    async def _capmonster(
        self, task_type: str, site_key: str, page_url: str, api_key: str, extra: dict | None = None
    ) -> str:
        """CapMonster Cloud — self-hosted option. Can run locally with 0 per-solve fees."""
        return await self._anti_captcha(
            task_type, site_key, page_url, api_key, extra
        )  # Same API as Anti-Captcha

    async def _deathbycaptcha(
        self, task_type: str, site_key: str, page_url: str, api_key: str, extra: dict | None = None
    ) -> str:
        """Solve via DeathByCaptcha API."""
        from client import get_client

        client = await get_client()
        user, pw = api_key.split(":", 1) if ":" in api_key else (api_key, "")
        method = {"ReCaptchaV2Task": "userrecaptcha", "HCaptchaTask": "hcaptcha"}.get(
            task_type, "userrecaptcha"
        )
        payload = {
            "username": user,
            "password": pw,
            "type": method,
            "token_params": json.dumps({"googlekey": site_key, "pageurl": page_url}),
        }
        resp = await client.post("https://api.dbcapi.me/api/captcha", data=payload, timeout=30)
        data = resp.json()
        if data.get("status") != 1:
            raise Exception(f"DBC error: {data}")
        captcha_id = data["captcha"]
        for _ in range(60):
            await asyncio.sleep(3)
            r = await client.get(f"https://api.dbcapi.me/api/captcha/{captcha_id}")
            rd = r.json()
            if rd.get("status") == 1:
                return rd["text"]
        raise Exception("DBC timed out")

    async def _nextcaptcha(
        self, task_type: str, site_key: str, page_url: str, api_key: str, extra: dict | None = None
    ) -> str:
        """Solve via NextCaptcha API."""
        from client import get_client

        client = await get_client()
        task_type_map = {
            "ReCaptchaV2Task": "RecaptchaV2TaskProxyless",
            "ReCaptchaV3Task": "RecaptchaV3TaskProxyless",
            "HCaptchaTask": "HCaptchaTaskProxyless",
            "TurnstileTask": "TurnstileTaskProxyless",
        }
        body = {
            "clientKey": api_key,
            "task": {
                "type": task_type_map.get(task_type, "RecaptchaV2TaskProxyless"),
                "websiteURL": page_url,
                "websiteKey": site_key,
            },
        }
        if extra:
            body["task"].update(extra)
        resp = await client.post("https://api.nextcaptcha.com/createTask", json=body, timeout=30)
        data = resp.json()
        if data.get("errorId") != 0:
            raise Exception(data.get("errorDescription", "NextCaptcha error"))
        task_id = data["taskId"]
        for _ in range(60):
            await asyncio.sleep(2)
            r = await client.post(
                "https://api.nextcaptcha.com/getTaskResult",
                json={"clientKey": api_key, "taskId": task_id},
            )
            rd = r.json()
            if rd.get("status") == "ready":
                return rd["solution"].get("gRecaptchaResponse", "")
            if rd.get("errorId") != 0:
                raise Exception(rd.get("errorDescription", ""))
        raise Exception("NextCaptcha timed out")

    async def _solve_image_with(
        self, provider: str, image_base64: str, api_key: str, case_sensitive: bool
    ) -> str:
        if provider == "capsolver":
            return await self._capsolver_image(image_base64, api_key, case_sensitive)
        elif provider == "2captcha":
            return await self._two_captcha_image(image_base64, api_key, case_sensitive)
        raise ValueError(f"Image solving not supported for {provider}")

    async def _capsolver_image(self, image_base64: str, api_key: str, case_sensitive: bool) -> str:
        from client import get_client

        client = await get_client()
        body = (
            image_base64 if not image_base64.startswith("data:") else image_base64.split(",", 1)[1]
        )
        resp = await client.post(
            "https://api.capsolver.com/createTask",
            json={"clientKey": api_key, "task": {"type": "ImageToTextTask", "body": body[:100000]}},
            timeout=30,
        )
        data = resp.json()
        task_id = data.get("taskId")
        if not task_id:
            raise Exception(data.get("errorDescription", ""))
        for _ in range(30):
            await asyncio.sleep(2)
            r = await client.post(
                "https://api.capsolver.com/getTaskResult",
                json={"clientKey": api_key, "taskId": task_id},
            )
            rd = r.json()
            if rd.get("status") == "ready":
                return rd["solution"].get("text", "")
        raise Exception("Image solve timed out")

    async def _two_captcha_image(
        self, image_base64: str, api_key: str, case_sensitive: bool
    ) -> str:
        from client import get_client

        client = await get_client()
        body = (
            image_base64 if not image_base64.startswith("data:") else image_base64.split(",", 1)[1]
        )
        resp = await client.post(
            "https://2captcha.com/in.php",
            data={
                "key": api_key,
                "method": "base64",
                "body": body,
                "json": 1,
                "regsense": 1 if case_sensitive else 0,
            },
            timeout=30,
        )
        data = resp.json()
        if data.get("status") != 1:
            raise Exception(data.get("request", ""))
        request_id = data["request"]
        for _ in range(30):
            await asyncio.sleep(3)
            r = await client.get(
                f"https://2captcha.com/res.php?key={api_key}&action=get&id={request_id}&json=1"
            )
            rd = r.json()
            if rd.get("status") == 1:
                return rd["request"]
        raise Exception("Image solve timed out")

    def _record(self, provider: str, success: bool, elapsed: float, error: str = "") -> None:
        stats = self.provider_stats[provider]
        if success:
            stats["success"] += 1
            stats["avg_time"] = (
                stats["avg_time"] * (stats["success"] + stats["failed"] - 1) + elapsed
            ) / (stats["success"] + stats["failed"])
        else:
            stats["failed"] += 1
            stats["last_error"] = error[:100]

    def get_stats(self) -> dict[str, Any]:
        return {
            "providers": self.provider_stats,
            "healthy_providers": sum(1 for p in self.provider_stats.values() if p["failed"] < 3),
        }
