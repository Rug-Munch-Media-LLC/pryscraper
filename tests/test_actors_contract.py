"""Contract tests for every Apify actor package in ``actor_factory/actors``.

Each actor must ship a valid ``actor.json`` (spec, name, version,
dockerfile), a valid ``INPUT_SCHEMA.json`` that agrees with the inline
schema, a README, a ``src/main.py`` wired to the shared PPE runner, and a
dataset schema that covers the keys the handler actually pushes.

The suite is deliberately structural: it proves the package can build and
that declared inputs/outputs line up with the code, without network calls.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from actor_factory.processors import PROCESSORS

ACTORS_DIR = Path("actor_factory/actors")
ACTORS = sorted(p for p in ACTORS_DIR.iterdir() if p.is_dir())

# Actors intentionally left on the generic scrape path (no processor).
GENERIC_ACTORS = {"pry-universal-scraper"}

# Known gap ratchet: specialised actors generated with processor=None.
# MUST only ever shrink - never add a name to make CI green.
KNOWN_UNIMPLEMENTED: set[str] = set()

BASE_KEYS = {"url", "status", "method", "scraped_at", "error", "content", "metadata"}


def _actor_json(actor: Path) -> dict:
    return json.loads((actor / ".actor" / "actor.json").read_text())


def _schema(actor: Path) -> dict:
    return json.loads((actor / ".actor" / "INPUT_SCHEMA.json").read_text())


def _processor_name(actor: Path) -> str | None:
    src = (actor / "src" / "main.py").read_text()
    match = re.search(r'processor_name=("(\w+)"|None)', src)
    return match.group(2) if match and match.group(2) else None


def _processor_module(processor: str) -> Path:
    for candidate in Path("actor_factory").glob("processors_*.py"):
        if f"def process_{processor}(" in candidate.read_text():
            return candidate
    raise FileNotFoundError(f"no processor module defines process_{processor}")


def _subscript_keys(tree: ast.AST, function_name: str) -> set[str]:
    keys: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != function_name:
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Subscript):
                continue
            if not isinstance(sub.value, ast.Name) or sub.value.id != "item":
                continue
            if isinstance(sub.slice, ast.Constant) and isinstance(sub.slice.value, str):
                keys.add(sub.slice.value)
    return keys


def _emitted_keys(processor: str) -> set[str]:
    """Top-level ``item[...]`` keys assigned by a processor function."""
    module = _processor_module(processor)
    return _subscript_keys(ast.parse(module.read_text()), f"process_{processor}")

def test_actors_exist() -> None:
    assert len(ACTORS) >= 100, f"only {len(ACTORS)} actor packages found"


@pytest.mark.parametrize("actor", ACTORS, ids=[a.name for a in ACTORS])
def test_required_files_present(actor: Path) -> None:
    for rel in (
        ".actor/actor.json",
        ".actor/INPUT_SCHEMA.json",
        ".actor/Dockerfile",
        ".actor/README.md",
        ".actor/dataset_schema.json",
        ".actor/output_schema.json",
        "src/main.py",
    ):
        assert (actor / rel).is_file(), f"{actor.name} missing {rel}"


@pytest.mark.parametrize("actor", ACTORS, ids=[a.name for a in ACTORS])
def test_actor_json_valid(actor: Path) -> None:
    spec = _actor_json(actor)
    assert spec["actorSpecification"] == 1
    assert isinstance(spec["name"], str)
    assert spec["name"]
    assert re.fullmatch(r"\d+\.\d+", str(spec["version"])), spec["version"]
    assert (actor / ".actor" / spec["dockerfile"]).is_file()
    assert spec.get("title")
    assert spec.get("description")
    assert (spec.get("input") or {}).get("properties")


@pytest.mark.parametrize("actor", ACTORS, ids=[a.name for a in ACTORS])
def test_input_schema_valid_and_in_sync(actor: Path) -> None:
    schema = _schema(actor)
    assert schema["type"] == "object"
    props = schema["properties"]
    assert "urls" in props
    assert props["urls"]["type"] == "array"
    assert set(schema.get("required") or []) <= set(props)
    inline = (_actor_json(actor).get("input") or {})
    assert json.dumps(inline.get("properties"), sort_keys=True) == json.dumps(
        props, sort_keys=True
    ), "actor.json input block drifted from INPUT_SCHEMA.json"


def _handler_sources(actor: Path, processor: str | None) -> str:
    src = (actor / "src" / "main.py").read_text()
    sources = [src]
    # The runner is split: input normalisation lives in runner_flow/runner_urls.
    sources.extend(
        path.read_text() for path in Path("actor_factory").glob("runner*.py")
    )
    if processor:
        sources.extend(p.read_text() for p in Path("actor_factory").glob("processors_*.py"))
    return " ".join(sources)


@pytest.mark.parametrize("actor", ACTORS, ids=[a.name for a in ACTORS])
def test_handler_wired_to_runner_and_reads_required_inputs(actor: Path) -> None:
    src = (actor / "src" / "main.py").read_text()
    assert "PPEScraperRunner" in src
    assert "asyncio.run(main())" in src
    assert re.search(r'primary_event="[^"]+"', src), "missing PPE primary_event"
    processor = _processor_name(actor)
    assert processor is None or processor in PROCESSORS, f"unknown processor {processor}"

    handler_src = _handler_sources(actor, processor)
    for key in _schema(actor).get("required") or []:
        assert f'"{key}"' in handler_src or f"'{key}'" in handler_src, (
            f"{actor.name}: required input {key!r} is never read"
        )


@pytest.mark.parametrize("actor", ACTORS, ids=[a.name for a in ACTORS])
def test_dataset_schema_covers_emitted_keys(actor: Path) -> None:
    fields = json.loads((actor / ".actor" / "dataset_schema.json").read_text())["fields"]
    props = set(fields["properties"])
    assert props >= BASE_KEYS, f"{actor.name} missing base keys {BASE_KEYS - props}"
    processor = _processor_name(actor)
    if processor:
        missing = _emitted_keys(processor) - props
        assert not missing, f"{actor.name} dataset schema missing {sorted(missing)}"


@pytest.mark.parametrize("actor", ACTORS, ids=[a.name for a in ACTORS])
def test_no_new_unimplemented_processors(actor: Path) -> None:
    if _processor_name(actor) is not None or actor.name in GENERIC_ACTORS:
        return
    assert actor.name in KNOWN_UNIMPLEMENTED, (
        f"{actor.name} claims a capability but has no processor; "
        "implement one or add it to GENERIC_ACTORS with justification"
    )


@pytest.mark.parametrize("actor", ACTORS, ids=[a.name for a in ACTORS])
def test_generic_actors_declare_explicit_limitations(actor: Path) -> None:
    """A processor-less actor may only ship if its README is explicit.

    The generic runner cannot honour a specialised promise, so those actors
    must state their limits in a ``## Limitations`` section with real bullets
    rather than inheriting generic copy.
    """
    if _processor_name(actor) is not None:
        return
    readme = (actor / ".actor" / "README.md").read_text()
    assert "## Limitations" in readme, f"{actor.name}: no Limitations section"
    section = readme.split("## Limitations", 1)[1].split("\n## ", 1)[0]
    bullets = [ln for ln in section.splitlines() if ln.strip().startswith("- ")]
    assert len(bullets) >= 2, (
        f"{actor.name}: generic actor must declare explicit limitations "
        "(at least two concrete bullets)"
    )


def test_unimplementable_capabilities_return_explicit_unavailable() -> None:
    """Token risk and sanctions actors must never fabricate a verdict."""
    from actor_factory.processors_web import process_sanctions, process_tokensafety

    token = process_tokensafety("https://etherscan.io", {"status": "ok"}, {}, {})
    sanctions = process_sanctions("https://sanctionssearch.ofac.treas.gov", {"status": "ok"}, {}, {})
    assert token["status"] == "unavailable"
    assert token["unavailable"] == "token_risk_feed_not_configured"
    assert token["signals"] == []
    assert sanctions["status"] == "unavailable"
    assert sanctions["unavailable"] == "sanctions_data_not_bundled"
    assert sanctions["matches"] == []


def test_ssl_probe_reports_failure_not_a_fake_certificate() -> None:
    from actor_factory.processors_web import process_sslcert

    item = process_sslcert("https://nonexistent.invalid", {"status": "ok"}, {"warn_days": 7}, {})
    assert item["status"] == "error"
    assert item["certificate"] == {}
    assert item["error"].startswith("tls_error:")
