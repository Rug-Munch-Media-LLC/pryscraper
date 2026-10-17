"""Branch coverage for API-key expiry, revocation scoping and listing."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from pry.core import api_keys_service as svc


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{tmp_path}/keys.db")
    import pry.core.db as db_pkg
    import pry.core.db.session as session_mod

    monkeypatch.setattr(db_pkg, "_engine", None, raising=False)
    monkeypatch.setattr(session_mod, "_engine", None, raising=False)
    from sqlalchemy import create_engine

    from pry.core.db import models as models_mod

    engine = create_engine(f"sqlite:///{tmp_path}/keys.db")
    models_mod.Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def test_expired_key_rejected(db) -> None:
    aware = svc.issue_key(name="expired", expires_at=datetime.now(UTC) - timedelta(minutes=1))
    assert svc.authenticate(aware["plaintext"]) is None


def test_authenticate_expiry_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)

    def run(expires_at):
        row = SimpleNamespace(
            key_id="k1",
            user_id="u1",
            name="n",
            scopes=["scrape"],
            rate_limit_rpm=60,
            quota_monthly=1000,
            expires_at=expires_at,
            last_used_at=None,
        )
        state = SimpleNamespace(commits=0)

        class _Query:
            def filter_by(self, **_kw):
                return self

            def first(self):
                return row

        class _Session:
            def query(self, _model):
                return _Query()

            def commit(self):
                state.commits += 1

        @contextmanager
        def fake_scope():
            yield _Session()

        monkeypatch.setattr(svc, "get_session", fake_scope)
        return svc.authenticate("pry_aaaa_bbbb"), state

    payload, state = run(now + timedelta(days=1))
    assert payload["key_id"] == "k1"
    assert state.commits == 1
    assert run(datetime.now() + timedelta(days=1))[0]["key_id"] == "k1"
    assert run(now - timedelta(minutes=1))[0] is None


def test_revoke_unknown_and_wrong_owner(db) -> None:
    assert svc.revoke_key("key_missing") is False
    issued = svc.issue_key(user_id="u1", name="owned")
    assert svc.revoke_key(issued["key_id"], user_id="u2") is False
    assert svc.revoke_key(issued["key_id"], user_id="u1") is True


def test_list_keys_filters_by_user(db) -> None:
    svc.issue_key(user_id="u1", name="a")
    svc.issue_key(user_id="u1", name="b")
    svc.issue_key(user_id="u2", name="c")
    rows = svc.list_keys("u2")
    assert [row["name"] for row in rows] == ["c"]
    assert rows[0]["user_id"] == "u2"
