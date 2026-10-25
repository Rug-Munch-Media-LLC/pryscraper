"""Tests for x402/facilitator.py — FacilitatorRouter, multi-provider fallback."""
from tests.x402._gate_support import db, no_owner_key  # noqa: F401
from tests.x402._x402_facilitator_support import _eip7702_ok, router  # noqa: F401
from pry.payments.x402.facilitator import FacilitatorConfig


def test_facilitator_config_required():
    cfg = FacilitatorConfig(
        name="test",
        verify_url="https://test/verify",
        settle_url="https://test/settle",
    )
    assert cfg.name == "test"
    assert cfg.verify_url == "https://test/verify"
    assert cfg.settle_url == "https://test/settle"
    assert cfg.priority == 0
    assert cfg.enabled is True
def test_facilitator_config_custom_priority():
    cfg = FacilitatorConfig(
        name="fast",
        verify_url="http://fast/verify",
        settle_url="http://fast/settle",
        priority=5,
        enabled=False,
    )
    assert cfg.priority == 5
    assert cfg.enabled is False
