"""Authorization matrix for every admin/PII route.

The admin surface exposes user PII (``/users``), payment records and operational
controls. It is mounted on one router whose access gate is a router-level
dependency, so a single forgotten ``Depends`` would expose every endpoint under
it. These tests pin the three outcomes that matter:

* anonymous (no credential)          -> 401 from the global auth middleware
* a valid but NON-admin user's key   -> 403 from the admin RBAC gate
* an ADMIN user's key                -> 200 on the read surface

Remote mode is used deliberately: on loopback the gate is bypassed by design,
which would make the RBAC assertions vacuous.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
# Part of Pry - https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

REMOTE = ("203.0.113.9", 51234)
MASTER = "master-key-for-admin-authz-tests"

#: Imported at module import: the routes are static and the auth matrix is
#: derived from them, so a newly added route is covered automatically.
from pry.api.routers.core.admin import router as admin_router  # noqa: E402

ROUTES = [
    (sorted(route.methods)[0], route.path)
    for route in admin_router.routes
    if getattr(route, "methods", None)
]
ROUTE_IDS = [f"{method} {path.rsplit('/v1/admin', 1)[-1] or '/'}" for method, path in ROUTES]

#: Read routes that need no path parameter and no request body.
READ_ROUTES = [(method, path) for method, path in ROUTES if method == "GET" and "{" not in path]
READ_IDS = [path.rsplit("/v1/admin", 1)[-1] or "/" for _method, path in READ_ROUTES]


def _concrete(path: str) -> str:
    """Replace path parameters with a value that cannot exist."""
    return (
        path.replace("{actor_name}", "no-such-actor")
        .replace("{user_id}", "no-such-user")
        .replace("{issue_id}", "no-such-issue")
        .replace("{key_id}", "no-such-key")
    )


def _request(client, method: str, path: str, **kwargs):
    return client.request(method, _concrete(path), **kwargs)


@pytest.fixture
def authz(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, str]]:
    """Remote-mode app with an admin user, a plain user, and both keys issued."""
    from sqlalchemy import create_engine

    import pry.api.routers.core.admin as admin_module
    import pry.core.api_keys_service as aks
    import pry.core.db as db_pkg
    import pry.core.db.models as models
    import pry.core.db.session as session_mod
    from pry.core.db.session import get_session
    from pry.core.settings import settings

    monkeypatch.setenv("PRY_DATABASE_URL", f"sqlite:///{tmp_path}/authz.db")
    monkeypatch.setenv("PRY_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(admin_module, "PRY_DATA_DIR", str(tmp_path))

    engine = create_engine(f"sqlite:///{tmp_path}/authz.db")
    models.Base.metadata.create_all(engine)
    # `pry.core.db.session` is a compatibility facade: the live state lives in
    # `db_engine`, and the facade only forwards *reads*. Patch the owner so
    # get_session() really uses this engine.
    import pry.core.db.db_engine as db_engine_mod
    from sqlalchemy.orm import sessionmaker

    monkeypatch.setattr(db_pkg, "_engine", engine, raising=False)
    monkeypatch.setattr(db_engine_mod, "_engine", engine, raising=False)
    monkeypatch.setattr(
        db_engine_mod,
        "_SessionLocal",
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False),
    )
    with get_session() as session:
        session.add(
            models.User(user_id="u_admin", email="admin@x.io", password_hash="x", role="ADMIN")
        )
        session.add(models.User(user_id="u_plain", email="plain@x.io", password_hash="x"))
        # The actor-detail route requires a DB row, not just a preset name.
        session.add(
            models.Actor(
                actor_id="authz-actor", name="Authz Actor", description="", author="test", tags=[]
            )
        )
        session.commit()

    def _issue(user_id: str) -> str:
        issued = aks.issue_key(user_id=user_id, name=f"{user_id}-key")
        return issued["plaintext"] if isinstance(issued, dict) else str(issued)

    # A configured master key makes anonymous remote calls 401 at the middleware
    # instead of reaching the gate (which would answer 403).
    monkeypatch.setattr(settings, "api_key", MASTER)
    monkeypatch.setattr(admin_module, "ADMIN_LOOPBACK_ONLY", False)

    yield {"admin": _issue("u_admin"), "plain": _issue("u_plain")}
    engine.dispose()


@pytest.fixture
def client(authz: dict[str, str]):
    from fastapi.testclient import TestClient

    from pry.api.api import app

    return TestClient(app, client=REMOTE, raise_server_exceptions=False)


class TestAdminAuthz:
    def test_every_route_is_mounted_with_the_admin_gate(self) -> None:
        """No admin route may exist without the gate dependency."""
        for route in admin_router.routes:
            names = {
                getattr(getattr(dep, "dependency", None), "__name__", "")
                for dep in getattr(route, "dependencies", []) or []
            }
            assert "_check_admin_access" in names, route.path

    @pytest.mark.parametrize(("method", "path"), ROUTES, ids=ROUTE_IDS)
    def test_anonymous_is_unauthenticated(self, client, method: str, path: str) -> None:
        response = _request(client, method, path)
        assert response.status_code == 401, (method, path, response.text[:120])

    @pytest.mark.parametrize(("method", "path"), ROUTES, ids=ROUTE_IDS)
    def test_non_admin_key_is_forbidden(
        self, client, authz: dict[str, str], method: str, path: str
    ) -> None:
        response = _request(
            client, method, path, headers={"authorization": f"Bearer {authz['plain']}"}
        )
        assert response.status_code == 403, (method, path, response.text[:120])

    @pytest.mark.parametrize(("method", "path"), READ_ROUTES, ids=READ_IDS)
    def test_admin_key_reads_succeed(
        self, client, authz: dict[str, str], method: str, path: str
    ) -> None:
        response = _request(
            client, method, path, headers={"authorization": f"Bearer {authz['admin']}"}
        )
        assert response.status_code == 200, (method, path, response.text[:120])

    def test_admin_key_reaches_pii_and_ping(self, client, authz: dict[str, str]) -> None:
        headers = {"authorization": f"Bearer {authz['admin']}"}
        prefix = admin_router.prefix
        assert client.get(f"{prefix}/v1/admin/users/u_admin", headers=headers).status_code == 200
        assert client.post(f"{prefix}/v1/admin/ping", json={}, headers=headers).status_code == 200
        detail = client.get(f"{prefix}/v1/admin/actors/authz-actor", headers=headers)
        assert detail.status_code == 200, detail.text[:120]
