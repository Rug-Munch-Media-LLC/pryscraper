
# SPDX-License-Identifier: BSL-1.1
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — Stealth / Anti-Detection Module
# Licensed under Business Source License 1.1 — see LICENSE-BSL-STEALTH.
# Change Date: 2029-01-01 (converts to MIT).
"""Pry — Signup automator with identity generation, email/SMS verification."""

import asyncio
import json
import logging
import random
import re
import string
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import httpx

logger = logging.getLogger(__name__)

PROFILES_DIR = Path(__file__).parent / "profiles"
PROFILES_DIR.mkdir(parents=True, exist_ok=True)


class ProfileGenerator:
    """Generate realistic human identities for account registration."""

    FIRST_NAMES: ClassVar[list[str]] = [
        "James",
        "Mary",
        "John",
        "Patricia",
        "Robert",
        "Jennifer",
        "Michael",
        "Linda",
        "William",
        "Elizabeth",
        "David",
        "Barbara",
        "Richard",
        "Susan",
        "Joseph",
        "Jessica",
        "Thomas",
        "Sarah",
        "Christopher",
        "Karen",
    ]
    LAST_NAMES: ClassVar[list[str]] = [
        "Smith",
        "Johnson",
        "Williams",
        "Brown",
        "Jones",
        "Garcia",
        "Miller",
        "Davis",
        "Rodriguez",
        "Martinez",
        "Hernandez",
        "Lopez",
        "Gonzalez",
        "Wilson",
        "Anderson",
        "Thomas",
        "Taylor",
        "Moore",
        "Jackson",
        "Martin",
    ]
    DOMAINS: ClassVar[list[str]] = [
        "gmail.com",
        "yahoo.com",
        "outlook.com",
        "hotmail.com",
        "protonmail.com",
        "icloud.com",
        "aol.com",
        "mail.com",
    ]
    STREETS: ClassVar[list[str]] = [
        "Oak",
        "Maple",
        "Cedar",
        "Pine",
        "Elm",
        "Birch",
        "Walnut",
        "Cherry",
        "Ash",
        "Willow",
    ]
    STREET_TYPES: ClassVar[list[str]] = [
        "St",
        "Ave",
        "Rd",
        "Dr",
        "Ln",
        "Blvd",
        "Way",
        "Ct",
        "Pl",
        "Cir",
    ]
    CITIES: ClassVar[list[str]] = [
        "New York",
        "Los Angeles",
        "Chicago",
        "Houston",
        "Phoenix",
        "Philadelphia",
        "San Antonio",
        "San Diego",
        "Dallas",
        "Austin",
        "Portland",
        "Seattle",
        "Denver",
        "Boston",
        "Nashville",
    ]
    STATES: ClassVar[list[str]] = [
        "NY",
        "CA",
        "IL",
        "TX",
        "AZ",
        "PA",
        "TX",
        "CA",
        "TX",
        "TX",
        "OR",
        "WA",
        "CO",
        "MA",
        "TN",
    ]
    JOBS: ClassVar[list[str]] = [
        "Software Engineer",
        "Teacher",
        "Nurse",
        "Accountant",
        "Marketing Manager",
        "Data Analyst",
        "Graphic Designer",
        "Project Manager",
        "Sales Associate",
        "Customer Support",
        "HR Coordinator",
        "Financial Analyst",
    ]

    def generate(self, locale: str = "US") -> dict[str, Any]:
        idx = random.randint(0, len(self.FIRST_NAMES) - 1)
        first = self.FIRST_NAMES[idx]
        last = random.choice(self.LAST_NAMES)
        username = (first + last + str(random.randint(10, 9999))).lower()
        email = f"{username}@{random.choice(self.DOMAINS)}"
        state_idx = random.randint(0, len(self.CITIES) - 1) if locale == "US" else 0
        profile = {
            "first_name": first,
            "last_name": last,
            "full_name": f"{first} {last}",
            "email": email,
            "username": username,
            "password": self._generate_password(),
            "phone": self._generate_phone(),
            "address": {
                "street": f"{random.randint(100, 9999)} {random.choice(self.STREETS)} {random.choice(self.STREET_TYPES)}",
                "city": self.CITIES[state_idx],
                "state": self.STATES[state_idx],
                "zip": f"{random.randint(10000, 99999)}",
                "country": "US",
            },
            "dob": f"{random.randint(1970, 2002)}-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}",
            "job_title": random.choice(self.JOBS),
            "created_at": datetime.now(UTC).isoformat(),
            "profile_id": self._generate_id(),
        }
        return profile

    def _generate_password(self, length: int = 16) -> str:
        chars = string.ascii_letters + string.digits + "!@#$%^&*"
        return "".join(random.choice(chars) for _ in range(length))

    def _generate_phone(self) -> str:
        return f"+1{random.randint(200, 999)}{random.randint(100, 999)}{random.randint(1000, 9999)}"

    def _generate_id(self) -> str:
        import uuid

        return uuid.uuid4().hex[:12]

    def save_profile(self, profile: dict[str, Any]) -> str:
        pid = profile["profile_id"]
        path = PROFILES_DIR / f"{pid}.json"
        path.write_text(json.dumps(profile, indent=2))
        return pid

    def load_profile(self, profile_id: str) -> dict[str, Any] | None:
        path = PROFILES_DIR / f"{profile_id}.json"
        if path.exists():
            return json.loads(path.read_text())
        return None


class EmailVerifier:
    """Handle email verification links via temp mail or IMAP."""

    def __init__(self, temp_mail_api_key: str = "", imap_config: dict[str, Any] | None = None):
        self.temp_mail_api_key = temp_mail_api_key
        self.imap_config = imap_config or {}

    async def create_temp_inbox(self) -> dict[str, Any]:
        """Create a temporary email inbox for receiving verification links."""
        from client import get_client

        client = await get_client()
        try:
            resp = await client.get("https://api.mail.tm/accounts", timeout=10)
            domains = resp.json().get("hydra:member", [])
            domain = domains[0]["domain"] if domains else "@mail.tm"
            import uuid

            name = f"pry_{uuid.uuid4().hex[:8]}"
            pw = uuid.uuid4().hex[:16]
            r = await client.post(
                "https://api.mail.tm/accounts",
                json={"address": f"{name}{domain}", "password": pw},
                timeout=10,
            )
            if r.is_success:
                token_r = await client.post(
                    "https://api.mail.tm/token",
                    json={"address": f"{name}{domain}", "password": pw},
                    timeout=10,
                )
                token = token_r.json().get("token", "")
                return {
                    "email": f"{name}{domain}",
                    "password": pw,
                    "token": token,
                    "provider": "mail.tm",
                }
        except (httpx.HTTPError, httpx.RequestError) as e:
            logger.warning("temp_mail_failed", extra={"error": str(e)[:80]})
        return {"email": "", "error": "Temp mail unavailable"}

    async def check_verification_link(
        self, token: str, max_wait: int = 120, check_interval: int = 5
    ) -> str | None:
        """Poll temp inbox for verification link."""
        from client import get_client

        client = await get_client()
        headers = {"Authorization": f"Bearer {token}"}
        for _ in range(max_wait // check_interval):
            try:
                r = await client.get("https://api.mail.tm/messages", headers=headers, timeout=10)
                if r.is_success:
                    messages = r.json().get("hydra:member", [])
                    for msg in messages:
                        msg_id = msg.get("id", "")
                        mr = await client.get(
                            f"https://api.mail.tm/messages/{msg_id}", headers=headers, timeout=10
                        )
                        if mr.is_success:
                            html = (
                                mr.json().get("html", [""])[0]
                                if isinstance(mr.json().get("html"), list)
                                else str(mr.json())
                            )
                            links = re.findall(r'https?://[^\s"<>]+', html)
                            for link in links:
                                if (
                                    "verify" in link.lower()
                                    or "confirm" in link.lower()
                                    or "activate" in link.lower()
                                ):
                                    return link
            except (httpx.HTTPError, httpx.RequestError):
                pass
            await asyncio.sleep(check_interval)
        return None


class SMSVerifier:
    """Handle SMS verification via Twilio or SMS-activate."""

    async def send_sms(
        self, phone: str, message: str, provider: str = "twilio", **creds: Any
    ) -> dict[str, Any]:
        if provider == "twilio":
            return await self._twilio_send(phone, message, creds)
        return {"success": False, "error": f"Unknown SMS provider: {provider}"}

    async def _twilio_send(self, phone: str, message: str, creds: dict) -> dict[str, Any]:
        from client import get_client

        client = await get_client()
        import base64

        auth = base64.b64encode(
            f"{creds.get('account_sid', '')}:{creds.get('auth_token', '')}".encode()
        ).decode()
        resp = await client.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{creds.get('account_sid', '')}/Messages.json",
            data={"To": phone, "From": creds.get("from_number", ""), "Body": message},
            headers={"Authorization": f"Basic {auth}"},
            timeout=15,
        )
        return {"success": resp.is_success, "status": resp.status_code}

    async def request_activation_number(self, service: str, country: str = "us") -> dict[str, Any]:
        """Get a phone number for SMS activation via SMS-activate.org."""
        from client import get_client

        api_key = self._get_key()
        if not api_key:
            return {"success": False, "error": "SMS-activate API key required"}
        client = await get_client()
        resp = await client.get(
            f"https://sms-activate.org/stubs/handler_api.php?api_key={api_key}&action=getNumber&service={service}&country={country}",
            timeout=15,
        )
        data = resp.text
        if "ACCESS_NUMBER" in data:
            parts = data.split(":")
            return {"success": True, "activation_id": parts[1], "phone": f"+{parts[2]}"}
        return {"success": False, "error": data}

    def _get_key(self) -> str:
        import os

        return os.getenv("PRY_SMS_ACTIVATE_KEY", "")
