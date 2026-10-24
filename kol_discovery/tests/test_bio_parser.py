"""Bio parser tests (fixtures are synthetic — see tests/fixtures/bios.json)."""

from __future__ import annotations

import json
from pathlib import Path

from kol_discovery.bios import parse_bio

FIXTURES = Path(__file__).parent / "fixtures"


def _rows() -> list[dict]:
    return json.loads((FIXTURES / "bios.json").read_text(encoding="utf-8"))["accounts"]


def test_cashtags_upper_and_deduped() -> None:
    facts = parse_bio("$wif $WIF $bonk going up $1 $ ")
    assert facts.cashtags == ["WIF", "BONK"]


def test_promo_phrases_detected_case_insensitively() -> None:
    facts = parse_bio("DM FOR PROMO and shill package available")
    assert "dm for promo" in facts.promo_phrases
    assert "shill package" in facts.promo_phrases
    assert facts.is_promo_account is True


def test_disclosure_marker_detected() -> None:
    assert parse_bio("paid shill #ad").discloses_promos is True
    assert parse_bio("paid shill, no labels").discloses_promos is False


def test_empty_and_none_bios_never_raise() -> None:
    for value in ("", None, "   "):
        facts = parse_bio(value)  # type: ignore[arg-type]
        assert facts.cashtags == []
        assert facts.token_contracts == []
        assert facts.is_promo_account is False


def test_fixture_bios_parse_without_crashing() -> None:
    parsed = [parse_bio(row["bio"]) for row in _rows()]
    assert len(parsed) == 3
    assert parsed[0].labelled_wallets, "PromoKing bio labels its wallet"
    assert parsed[0].telegrams == ["promokinggg"]
