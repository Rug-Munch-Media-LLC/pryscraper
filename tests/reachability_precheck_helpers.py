"""Shared probe-stub installers for the reachability-precheck tests.

Hoisted because three test files need the same stubs and duplicating them pushed
each over the 200-line cap. Pure: installs fakes, opens no sockets.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - annotations only
    import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from pry.engine import reachability_precheck as rp  # noqa: E402
from scripts.target_reachability import (  # noqa: E402
    TargetProbe,
    blame_tier,
    classify,
    host_of,
)

HOST = "unreachable.invalid"


def _stub_raising(exc: BaseException) -> Any:
    """A classifier that blows up the way a real probe can."""

    def _boom(*_a: Any, **_kw: Any) -> Any:
        raise exc

    return type(
        "_Stub",
        (),
        {
            "host_of": staticmethod(lambda _url: HOST),
            "precheck_dns_and_tcp": staticmethod(_boom),
            "classify": staticmethod(classify),
            "blame_tier": staticmethod(blame_tier),
        },
    )()


def _stub(probe: TargetProbe, host: str | None = None) -> Any:
    """A classifier whose probe is a fixed, already-observed fact.

    ``host`` defaults to :data:`HOST`; pass one to model a target whose cert
    covers its own name, or ``None`` to use the real extractor.
    """
    return type(
        "_Stub",
        (),
        {
            "host_of": staticmethod(host_of if host is None else lambda _url: host),
            "precheck_dns_and_tcp": staticmethod(lambda *_a, **_kw: probe),
            "classify": staticmethod(classify),
            "blame_tier": staticmethod(blame_tier),
        },
    )()


def _install(monkeypatch: pytest.MonkeyPatch, stub: Any) -> None:
    monkeypatch.setattr(rp, "_load_classifier", lambda: stub)
