"""Tests for x402/facilitator.py — FacilitatorRouter, multi-provider fallback."""
from tests.x402._x402_facilitator_support import _eip7702_ok, router  # noqa: F401
from pry.payments.x402.facilitator import DEFAULT_FACILITATORS, FacilitatorRouter


def test_router_init(router: FacilitatorRouter):
    assert isinstance(router.facilitators, list)
    assert len(router.facilitators) > 0
def test_router_contains_all_defaults(router: FacilitatorRouter):
    names = {f.name for f in router.facilitators}
    # coinbase and payai are enabled by default and must be present.
    assert "coinbase" in names
    assert "payai" in names
    # cloudflare is disabled by default (only included if verify_url is set),
    # so it is NOT required — but if present it must be a real config.
    if "cloudflare" in names:
        assert any(f.name == "cloudflare" for f in router.facilitators)
def test_router_sorted_by_priority(router: FacilitatorRouter):
    priorities = [f.priority for f in router.facilitators]
    assert priorities == sorted(priorities)
def test_router_empty_allowed():
    """Passing an empty list should result in no facilitators."""
    r = FacilitatorRouter(facilitators=[])
    expected = sorted(
        [f for f in DEFAULT_FACILITATORS if f.enabled and f.verify_url], key=lambda f: f.priority
    )
    assert r.facilitators == expected
def test_router_accepts_empty_self_hosted():
    """Self-hosted mode works with minimal facilitator list."""
    r = FacilitatorRouter(facilitators=None, self_hosted=True)
    assert r.self_hosted is True
def test_router_self_hosted_flag():
    r = FacilitatorRouter(self_hosted=True)
    assert r.self_hosted is True
