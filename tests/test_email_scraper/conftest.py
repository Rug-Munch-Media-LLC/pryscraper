# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Fake Gmail/Graph client used by the email-scraper fetch tests."""


class _FakeResponse:
    def __init__(self, is_success: bool, payload: object = None, text: str = "") -> None:
        self.is_success = is_success
        self._payload = payload
        self.text = text
        self.status_code = 200

    def json(self) -> object:
        return self._payload


class _FakeClient:
    """Client that lists N messages and fails the fetch of a chosen subset."""

    def __init__(self, message_ids: list[str], failing: set[str]) -> None:
        self.message_ids = message_ids
        self.failing = failing

    async def get(self, url: str, **kwargs: object) -> _FakeResponse:
        if url.endswith("/messages"):
            return _FakeResponse(True, {"messages": [{"id": m} for m in self.message_ids]})
        msg_id = url.rsplit("/", 1)[-1]
        if msg_id in self.failing:
            return _FakeResponse(False, text=f"boom {msg_id}")
        return _FakeResponse(True, {"payload": {"headers": [], "body": {"parts": []}}})
