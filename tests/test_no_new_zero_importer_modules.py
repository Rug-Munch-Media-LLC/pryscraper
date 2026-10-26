# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
"""Guard: zero-importer modules under ``src/pry`` must not grow silently.

Baseline measured 2026-10-25 after removing the three repointed facades
(``misc/x402.py``, ``engine/scraping_methods.py``, ``misc/signup_automation.py``)
— see ``docs/DEAD-CODE-EVIDENCE.md``. A module is "zero-importer" when no other
``.py`` file in the repo imports it and nothing references it by dotted string.

The ratchet is bidirectional and only shrinks:
  * a NEW zero-importer module fails the gate — wire an importer, or add it to
    ``BASELINE`` together with a written reason;
  * a ``BASELINE`` entry that gained an importer also fails — delete the entry.

Excluded on purpose: package ``__init__.py`` files (an initializer is a
structural marker, not a leaf module), this file (its BASELINE *is* a list of
names, not imports), and markdown/docs references (code references only).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SELF = Path(__file__).resolve()
SKIP = {
    "build",
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "site-packages",
}
DYN = re.compile(r"\bpry(?:\.[A-Za-z_]\w*)*\b")

BASELINE: dict[str, str] = {
    "pry.actors.apify_actor.__main__": "has __main__ guard = runnable operator script",
    "pry.commerce.reconciliation.llm": "zero-importer leaf of live package pry.commerce.reconciliation — measured 2026-10-25, removal needs owner sign-off",
    "pry.commerce.reconciliation.normalization": "zero-importer leaf of live package pry.commerce.reconciliation — measured 2026-10-25, removal needs owner sign-off",
    "pry.commerce.reconciliation.schemas": "zero-importer leaf of live package pry.commerce.reconciliation — measured 2026-10-25, removal needs owner sign-off",
    "pry.commerce.signup.form_detection.fields": "zero-importer leaf of live package pry.commerce.signup.form_detection — measured 2026-10-25, removal needs owner sign-off",
    "pry.commerce.signup.form_detection.models": "zero-importer leaf of live package pry.commerce.signup.form_detection — measured 2026-10-25, removal needs owner sign-off",
    "pry.commerce.signup.form_detection.parser": "zero-importer leaf of live package pry.commerce.signup.form_detection — measured 2026-10-25, removal needs owner sign-off",
    "pry.commerce.signup.form_detection.roles": "zero-importer leaf of live package pry.commerce.signup.form_detection — measured 2026-10-25, removal needs owner sign-off",
    "pry.commerce.templates.test_live": "has __main__ guard = runnable operator script",
    "pry.commerce.templates.validate_live": "has __main__ guard = runnable operator script",
    "pry.commerce.templates.validate_templates": "has __main__ guard = runnable operator script",
    "pry.engine.site_mapper": "referenced in ./AGENTS.md",
    "pry.intelligence.llm.providers.anthropic": "zero-importer leaf of live package pry.intelligence.llm.providers — measured 2026-10-25, removal needs owner sign-off",
    "pry.intelligence.llm.providers.cerebras": "zero-importer leaf of live package pry.intelligence.llm.providers — measured 2026-10-25, removal needs owner sign-off",
    "pry.intelligence.llm.providers.cohere": "zero-importer leaf of live package pry.intelligence.llm.providers — measured 2026-10-25, removal needs owner sign-off",
    "pry.intelligence.llm.providers.deepseek": "zero-importer leaf of live package pry.intelligence.llm.providers — measured 2026-10-25, removal needs owner sign-off",
    "pry.intelligence.llm.providers.defaults": "zero-importer leaf of live package pry.intelligence.llm.providers — measured 2026-10-25, removal needs owner sign-off",
    "pry.intelligence.llm.providers.google": "zero-importer leaf of live package pry.intelligence.llm.providers — measured 2026-10-25, removal needs owner sign-off",
    "pry.intelligence.llm.providers.groq": "zero-importer leaf of live package pry.intelligence.llm.providers — measured 2026-10-25, removal needs owner sign-off",
    "pry.intelligence.llm.providers.kilocode": "zero-importer leaf of live package pry.intelligence.llm.providers — measured 2026-10-25, removal needs owner sign-off",
    "pry.intelligence.llm.providers.kimi": "zero-importer leaf of live package pry.intelligence.llm.providers — measured 2026-10-25, removal needs owner sign-off",
    "pry.intelligence.llm.providers.local": "zero-importer leaf of live package pry.intelligence.llm.providers — measured 2026-10-25, removal needs owner sign-off",
    "pry.intelligence.llm.providers.minimax": "zero-importer leaf of live package pry.intelligence.llm.providers — measured 2026-10-25, removal needs owner sign-off",
    "pry.intelligence.llm.providers.mistral": "zero-importer leaf of live package pry.intelligence.llm.providers — measured 2026-10-25, removal needs owner sign-off",
    "pry.intelligence.llm.providers.nous": "zero-importer leaf of live package pry.intelligence.llm.providers — measured 2026-10-25, removal needs owner sign-off",
    "pry.intelligence.llm.providers.nvidia": "zero-importer leaf of live package pry.intelligence.llm.providers — measured 2026-10-25, removal needs owner sign-off",
    "pry.intelligence.llm.providers.openai": "zero-importer leaf of live package pry.intelligence.llm.providers — measured 2026-10-25, removal needs owner sign-off",
    "pry.intelligence.llm.providers.opencode_zen": "zero-importer leaf of live package pry.intelligence.llm.providers — measured 2026-10-25, removal needs owner sign-off",
    "pry.intelligence.llm.providers.openrouter": "zero-importer leaf of live package pry.intelligence.llm.providers — measured 2026-10-25, removal needs owner sign-off",
    "pry.intelligence.llm.providers.siliconflow": "zero-importer leaf of live package pry.intelligence.llm.providers — measured 2026-10-25, removal needs owner sign-off",
    "pry.intelligence.llm.providers.zai": "zero-importer leaf of live package pry.intelligence.llm.providers — measured 2026-10-25, removal needs owner sign-off",
    "pry.payments.reconciliation_sql": "unique behaviour, zero importers and zero refs",
    "pry.payments.x402.addresses": "zero-importer leaf of live package pry.payments.x402 — measured 2026-10-25, removal needs owner sign-off",
    "pry.payments.x402.helpers": "zero-importer leaf of live package pry.payments.x402 — measured 2026-10-25, removal needs owner sign-off",
    "pry.payments.x402.scheme.attestation": "zero-importer leaf of live package pry.payments.x402.scheme — measured 2026-10-25, removal needs owner sign-off",
    "pry.payments.x402.scheme.attestation_binding": "zero-importer leaf of live package pry.payments.x402.scheme — measured 2026-10-25, removal needs owner sign-off",
    "pry.payments.x402.scheme.attestation_verify": "zero-importer leaf of live package pry.payments.x402.scheme — measured 2026-10-25, removal needs owner sign-off",
    "pry.payments.x402.scheme.enums": "zero-importer leaf of live package pry.payments.x402.scheme — measured 2026-10-25, removal needs owner sign-off",
    "pry.payments.x402.scheme.networks_evm": "zero-importer leaf of live package pry.payments.x402.scheme — measured 2026-10-25, removal needs owner sign-off",
    "pry.payments.x402.scheme.networks_solana": "zero-importer leaf of live package pry.payments.x402.scheme — measured 2026-10-25, removal needs owner sign-off",
    "pry.payments.x402.scheme.networks_tron": "zero-importer leaf of live package pry.payments.x402.scheme — measured 2026-10-25, removal needs owner sign-off",
    "pry.payments.x402.scheme.oracle": "zero-importer leaf of live package pry.payments.x402.scheme — measured 2026-10-25, removal needs owner sign-off",
    "pry.payments.x402.scheme.pricing.accepts": "zero-importer leaf of live package pry.payments.x402.scheme.pricing — measured 2026-10-25, removal needs owner sign-off",
    "pry.payments.x402.scheme.pricing.challenge": "zero-importer leaf of live package pry.payments.x402.scheme.pricing — measured 2026-10-25, removal needs owner sign-off",
    "pry.payments.x402.scheme.pricing.context": "zero-importer leaf of live package pry.payments.x402.scheme.pricing — measured 2026-10-25, removal needs owner sign-off",
    "pry.payments.x402.scheme.pricing.legacy": "zero-importer leaf of live package pry.payments.x402.scheme.pricing — measured 2026-10-25, removal needs owner sign-off",
    "pry.payments.x402.scheme.pricing.legacy_accepts": "zero-importer leaf of live package pry.payments.x402.scheme.pricing — measured 2026-10-25, removal needs owner sign-off",
    "pry.payments.x402.scheme.pricing.manifest": "zero-importer leaf of live package pry.payments.x402.scheme.pricing — measured 2026-10-25, removal needs owner sign-off",
    "pry.payments.x402.self_facilitator.crypto": "zero-importer leaf of live package pry.payments.x402.self_facilitator — measured 2026-10-25, removal needs owner sign-off",
    "pry.payments.x402.self_facilitator.evm": "zero-importer leaf of live package pry.payments.x402.self_facilitator — measured 2026-10-25, removal needs owner sign-off",
    "pry.payments.x402.self_facilitator.evm_common": "zero-importer leaf of live package pry.payments.x402.self_facilitator — measured 2026-10-25, removal needs owner sign-off",
    "pry.payments.x402.self_facilitator.evm_rpc": "zero-importer leaf of live package pry.payments.x402.self_facilitator — measured 2026-10-25, removal needs owner sign-off",
    "pry.payments.x402.self_facilitator.evm_settle": "zero-importer leaf of live package pry.payments.x402.self_facilitator — measured 2026-10-25, removal needs owner sign-off",
    "pry.payments.x402.self_facilitator.evm_trackers": "zero-importer leaf of live package pry.payments.x402.self_facilitator — measured 2026-10-25, removal needs owner sign-off",
    "pry.payments.x402.self_facilitator.networks": "zero-importer leaf of live package pry.payments.x402.self_facilitator — measured 2026-10-25, removal needs owner sign-off",
    "pry.payments.x402.self_facilitator.nonces": "zero-importer leaf of live package pry.payments.x402.self_facilitator — measured 2026-10-25, removal needs owner sign-off",
    "pry.payments.x402.self_facilitator.pricing": "zero-importer leaf of live package pry.payments.x402.self_facilitator — measured 2026-10-25, removal needs owner sign-off",
    "pry.payments.x402.self_facilitator.response": "zero-importer leaf of live package pry.payments.x402.self_facilitator — measured 2026-10-25, removal needs owner sign-off",
    "pry.payments.x402.solana_transfer.candidates": "zero-importer leaf of live package pry.payments.x402.solana_transfer — measured 2026-10-25, removal needs owner sign-off",
    "pry.payments.x402.solana_transfer.request": "zero-importer leaf of live package pry.payments.x402.solana_transfer — measured 2026-10-25, removal needs owner sign-off",
    "pry.payments.x402.solana_transfer.rpc": "zero-importer leaf of live package pry.payments.x402.solana_transfer — measured 2026-10-25, removal needs owner sign-off",
    "pry.payments.x402.solana_transfer.verify": "zero-importer leaf of live package pry.payments.x402.solana_transfer — measured 2026-10-25, removal needs owner sign-off",
    "pry.payments.x402.tokens": "zero-importer leaf of live package pry.payments.x402 — measured 2026-10-25, removal needs owner sign-off",
}


def _modules() -> dict[str, Path]:
    return {
        ".".join(path.relative_to(SRC).with_suffix("").parts): path
        for path in (SRC / "pry").rglob("*.py")
        if path.name != "__init__.py"
    }


def _names_imported_by(text: str) -> set[str]:
    found: set[str] = set(DYN.findall(text))
    try:
        tree: ast.AST | None = ast.parse(text)
    except SyntaxError:
        tree = None
    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                found.add(node.module)
                found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def _referenced(modules: dict[str, Path]) -> set[str]:
    referenced: set[str] = set()
    for path in ROOT.rglob("*.py"):
        if any(part in SKIP for part in path.relative_to(ROOT).parts) or path.resolve() == SELF:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        found = _names_imported_by(text)
        referenced.update(m for m, own in modules.items() if m in found and path != own)
    return referenced


def test_no_new_zero_importer_modules() -> None:
    """Every zero-importer module is allowlisted with a reason; allowlist only shrinks."""
    modules = _modules()
    zero = {m for m in modules if m not in _referenced(modules)}
    new = sorted(zero - set(BASELINE))
    stale = sorted(set(BASELINE) - zero)
    assert not new, (
        f"new zero-importer modules - wire an importer or allowlist WITH a reason: {new}"
    )
    assert not stale, (
        f"baseline entries gained an importer - delete them (ratchet only shrinks): {stale}"
    )
