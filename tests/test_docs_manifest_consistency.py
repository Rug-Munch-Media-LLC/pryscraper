"""Docs and MCP registry manifests must agree with the code.

Guards four drift classes that shipped real bugs:
tool names that do not exist in PRY_TOOLS, dead repository URLs, a Smithery
start command naming a module that cannot be imported, and version/count
claims that contradict pyproject and the code.
"""

from __future__ import annotations

import importlib
import json
import re
import tomllib
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
CANONICAL_REPO = "https://git.rugmunch.io/RugMunchMedia/pryscraper"
TOOL_MANIFESTS = (
    "server.json",
    "glama.json",
    "pulsemcp.json",
    "registry_submissions/mcp_listing.json",
)
URL_DOCS = (*("README.md", "docs/QUICKSTART.md", "llms.txt", "smithery.yaml"), *TOOL_MANIFESTS)


def _pry_tools() -> list[dict]:
    from pry_mcp.tools import PRY_TOOLS

    return PRY_TOOLS


def _manifest_tool_names(path: Path) -> set[str]:
    data = json.loads(path.read_text())
    tools = data.get("tools", [])
    return {t["name"] if isinstance(t, dict) else t for t in tools}


def _versions() -> dict[str, str]:
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text())
    changelog = (REPO / "CHANGELOG.md").read_text()
    released = [
        m.group(1)
        for m in re.finditer(r"^## \[(\d+\.\d+\.\d+)\][^\n]*$", changelog, re.MULTILINE)
        if "unreleased" not in m.group(0).lower()
    ]
    newest = max(released, key=lambda v: tuple(int(p) for p in v.split(".")))
    return {
        "pyproject": pyproject["project"]["version"],
        "changelog": newest,
        "server.json": json.loads((REPO / "server.json").read_text())["version"],
        "glama.json": json.loads((REPO / "glama.json").read_text())["version"],
        "pulsemcp.json": json.loads((REPO / "pulsemcp.json").read_text())["version"],
        "mcp_listing.json": json.loads(
            (REPO / "registry_submissions/mcp_listing.json").read_text()
        )["version"],
    }


def test_manifest_tools_are_a_subset_of_pry_tools() -> None:
    real = {t["name"] for t in _pry_tools()}
    assert len(real) == 99
    for name in TOOL_MANIFESTS:
        listed = _manifest_tool_names(REPO / name)
        assert listed <= real, f"{name} lists unknown tools: {sorted(listed - real)}"
        assert listed == real, f"{name} is missing tools: {sorted(real - listed)}"


def test_no_dead_repository_urls() -> None:
    for name in URL_DOCS:
        text = (REPO / name).read_text()
        assert "codeberg.org" not in text, f"{name} still points at a dead Forgejo mirror"
    assert CANONICAL_REPO in (REPO / "README.md").read_text()
    assert CANONICAL_REPO in (REPO / "docs/QUICKSTART.md").read_text()


def test_smithery_command_module_imports() -> None:
    cfg = yaml.safe_load((REPO / "smithery.yaml").read_text())
    command = cfg["startCommand"]["commandFunction"]
    module = re.search(r"'-m',\s*'([\w.]+)'", command)
    assert module, "smithery.yaml commandFunction must launch a module with -m"
    importlib.import_module(module.group(1))


def test_versions_and_documented_counts_match_code() -> None:
    versions = _versions()
    assert len(set(versions.values())) == 1, f"version drift: {versions}"

    tools = _pry_tools()
    templates = len(list((REPO / "src/pry/commerce/templates").glob("*.json")))
    assert templates == 110

    llms = (REPO / "llms.txt").read_text()
    assert f"Tools: {len(tools)}" in llms
    assert "Categories: 33" in llms

    catalog = (REPO / "docs/ops/TOOLS-CATALOG.md").read_text()
    assert f"**Totals: {len(tools)} tools across 33 categories.**" in catalog
    assert "(99 tools" not in catalog  # stale per-section headers
    assert f"{templates} templates" in (REPO / "README.md").read_text()
