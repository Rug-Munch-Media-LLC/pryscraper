"""Public-bio parsing: cashtags, token contracts, links, telegram, promo cues.

Deliberate distinction enforced here: a bare address in a bio is treated as a
**token contract** (what KOLs shill), never as the KOL's own wallet. A wallet
is only produced when the bio labels it (``wallet:``, ``sol:``, ``address:``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CASHTAG_RE = re.compile(r"\$([A-Za-z][A-Za-z0-9]{1,9})\b")
SOLANA_RE = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")
EVM_RE = re.compile(r"\b0x[0-9a-fA-F]{40}\b")
TG_RE = re.compile(r"(?:https?://)?t\.me/([A-Za-z0-9_]{4,32})", re.I)
URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
HANDLE_RE = re.compile(r"(?<![\w/])@([A-Za-z0-9_]{2,15})\b")

PROMO_PHRASES = (
    "dm for promo",
    "dm for collab",
    "dm for paid",
    "paid promo",
    "paid shill",
    "promo slots",
    "shill package",
    "dm to promote",
    "dm for partnership",
    "promo available",
)
DISCLOSURE_MARKERS = ("#ad", "#sponsored", "#paid", "paid partnership", "sponsored")

WALLET_LABEL_RE = re.compile(
    r"(?:\b(?:wallet|sol|solana|addr|address|evm|eth)\b\s*[:=]\s*)"
    r"([1-9A-HJ-NP-Za-km-z]{32,44}|0x[0-9a-fA-F]{40})",
    re.I,
)


@dataclass
class BioFacts:
    cashtags: list[str] = field(default_factory=list)
    token_contracts: list[str] = field(default_factory=list)
    labelled_wallets: list[str] = field(default_factory=list)
    telegrams: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    mentions: list[str] = field(default_factory=list)
    promo_phrases: list[str] = field(default_factory=list)
    discloses_promos: bool = False

    @property
    def is_promo_account(self) -> bool:
        return bool(self.promo_phrases)

    def to_dict(self) -> dict[str, object]:
        return {
            "cashtags": list(self.cashtags),
            "token_contracts": list(self.token_contracts),
            "labelled_wallets": list(self.labelled_wallets),
            "telegrams": list(self.telegrams),
            "links": list(self.links),
            "mentions": list(self.mentions),
            "promo_phrases": list(self.promo_phrases),
            "discloses_promos": self.discloses_promos,
        }


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        marker = value.casefold()
        if marker and marker not in seen:
            seen.add(marker)
            out.append(value)
    return out


def parse_bio(bio: str) -> BioFacts:
    """Extract facts from a public bio. Never raises on odd input."""
    text = bio or ""
    lowered = text.casefold()

    labelled = [m.group(1) for m in WALLET_LABEL_RE.finditer(text)]
    labelled_set = {addr.casefold() for addr in labelled}

    contracts = EVM_RE.findall(text) + SOLANA_RE.findall(text)
    contracts = [c for c in contracts if c.casefold() not in labelled_set]

    promos = [p for p in PROMO_PHRASES if p in lowered]
    links = _dedupe([u.rstrip(".,);") for u in URL_RE.findall(text)])

    return BioFacts(
        cashtags=_dedupe([t.upper() for t in CASHTAG_RE.findall(text)]),
        token_contracts=_dedupe(contracts),
        labelled_wallets=_dedupe(labelled),
        telegrams=_dedupe([m.group(1) for m in TG_RE.finditer(text)]),
        links=links,
        mentions=_dedupe([m.group(1) for m in HANDLE_RE.finditer(text)]),
        promo_phrases=promos,
        discloses_promos=any(marker in lowered for marker in DISCLOSURE_MARKERS),
    )
