# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Monitoring assets must reference metrics that actually exist.

A dashboard panel or alert rule naming a metric nobody emits is not a cosmetic
bug: it renders as an empty panel and an alert that can never fire. These tests
bind the three artefacts — Prometheus rules, Grafana dashboard, SLO doc — to the
metric names found in ``src/pry`` and to the compose mounts that load them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "pry"
COMPOSE = ROOT / "compose.monitoring.yml"
ALERTS = ROOT / "prometheus" / "alerts.yml"
PROM_CONFIG = ROOT / "prometheus" / "prometheus.yml"
DASHBOARD = ROOT / "grafana" / "dashboards" / "pry-slo.json"
SLO_DOC = ROOT / "docs" / "ops" / "SLO.md"

METRIC_RE = re.compile(r"(?<![$\w.])(pry_[a-z0-9_]+|x402_[a-z0-9_]+)")
INFRA_METRICS = {"up", "probe_success", "time"}


def emitted_metrics() -> set[str]:
    """Metric names declared anywhere in application source."""
    names: set[str] = set()
    for path in SRC.rglob("*.py"):
        names.update(METRIC_RE.findall(path.read_text(encoding="utf-8", errors="ignore")))
    return names


def referenced(expr: str) -> set[str]:
    """Metric series referenced by one PromQL expression (buckets normalised)."""
    found = set()
    for name in METRIC_RE.findall(expr):
        found.add(name.removesuffix("_bucket").removesuffix("_sum").removesuffix("_count"))
    return found


def _alert_exprs() -> list[tuple[str, str]]:
    doc = yaml.safe_load(ALERTS.read_text(encoding="utf-8"))
    out: list[tuple[str, str]] = []
    for group in doc["groups"]:
        for rule in group["rules"]:
            out.append((rule["alert"], "".join(str(rule["expr"]).split())))
    return out


def test_every_alert_metric_is_emitted() -> None:
    emitted = emitted_metrics()
    missing = {
        metric: alert
        for alert, expr in _alert_exprs()
        for metric in referenced(expr)
        if metric not in emitted
    }
    assert not missing, f"alerts cite metrics not emitted by src/pry: {missing}"


def test_alert_rules_have_required_fields() -> None:
    doc = yaml.safe_load(ALERTS.read_text(encoding="utf-8"))
    for group in doc["groups"]:
        assert group["rules"], f"empty group {group['name']}"
        for rule in group["rules"]:
            assert rule["expr"].strip(), rule["alert"]
            assert rule["labels"]["severity"] in {"critical", "warning"}, rule["alert"]
            assert rule["annotations"]["summary"], rule["alert"]


def test_slo_document_metrics_are_emitted() -> None:
    text = SLO_DOC.read_text(encoding="utf-8")
    # Only inline code spans are metric references; fenced blocks are formulas
    # and prose mentions alert names.
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    spans = re.findall(r"`([^`]+)`", text)
    tokens = {m for span in spans for m in METRIC_RE.findall(span)}
    missing = {t for t in tokens if t.removesuffix("_bucket") not in emitted_metrics()}
    assert not missing, f"SLO.md cites metrics not emitted: {missing}"


def _resolve_targets(panels: list[dict]) -> tuple[int, dict[str, str]]:
    emitted = emitted_metrics()
    unresolved: dict[str, str] = {}
    targets = 0
    for panel in panels:
        for target in panel.get("targets", []):
            expr = target.get("expr")
            if not expr:
                continue
            targets += 1
            for metric in referenced(expr):
                if metric not in emitted:
                    unresolved[metric] = panel["title"]
    return targets, unresolved


def test_dashboard_parses_and_panels_resolve() -> None:
    doc = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    assert doc["uid"] == "pry-slo"
    panels = doc["panels"]
    assert len(panels) >= 15
    assert len({p["id"] for p in panels}) == len(panels), "duplicate panel ids"
    targets, unresolved = _resolve_targets(panels)
    assert targets >= 15, f"only {targets} query targets in dashboard"
    assert not unresolved, f"dashboard queries unknown metrics: {unresolved}"

def test_queue_metrics_are_emitted_by_collector() -> None:
    from pry.core.observability import JobQueueCollector

    families = {f.name for f in JobQueueCollector().collect()}
    assert families == {"pry_queue_depth", "pry_queue_oldest_job_age_seconds"}


def _mounts(service: str) -> dict[str, Path]:
    """Container path -> host path for one compose service (dirs and files)."""
    doc = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    mapping: dict[str, Path] = {}
    for volume in doc["services"][service].get("volumes", []):
        host, _, container = str(volume).partition(":")
        if not host.startswith("."):
            continue  # named volume, not a repo path
        mapping[container.split(":")[0]] = ROOT / host.lstrip("./")
    return mapping


def test_provisioning_sources_exist() -> None:
    for service in ("prometheus", "alertmanager", "grafana"):
        for container, host in _mounts(service).items():
            assert host.exists(), f"{service}: missing source for {container}: {host}"


def test_prometheus_rule_files_are_mounted() -> None:
    config = yaml.safe_load(PROM_CONFIG.read_text(encoding="utf-8"))
    mounts = _mounts("prometheus")
    for rule_file in config["rule_files"]:
        assert rule_file in mounts, f"rule_files {rule_file} is not mounted by compose"
        assert yaml.safe_load(mounts[rule_file].read_text(encoding="utf-8"))["groups"]


def test_alertmanager_target_is_a_defined_service() -> None:
    config = yaml.safe_load(PROM_CONFIG.read_text(encoding="utf-8"))
    target = config["alerting"]["alertmanagers"][0]["static_configs"][0]["targets"][0]
    host = target.rsplit(":", 1)[0]
    doc = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    assert host in doc["services"], f"alertmanager host {host} is not in the compose stack"


def test_grafana_dashboards_are_provisioned() -> None:
    mounts = _mounts("grafana")
    provider_dirs = [p for p in mounts if p.endswith("/provisioning/dashboards")]
    assert provider_dirs, "grafana dashboard provider dir is not mounted"

    provider_file = ROOT / "grafana" / "dashboards" / "dashboard.yml"
    provider = yaml.safe_load(provider_file.read_text(encoding="utf-8"))
    path = provider["providers"][0]["options"]["path"]
    assert path in provider_dirs, f"provider path {path} is not a compose mount"
    assert any(p.suffix == ".json" for p in (ROOT / "grafana" / "dashboards").iterdir())

    datasources = [p for p in mounts if p.endswith("/provisioning/datasources")]
    assert datasources, "grafana datasource dir is not mounted"
    ds = yaml.safe_load((ROOT / "grafana" / "datasources" / "prometheus.yml").read_text())
    assert ds["datasources"][0]["url"] == "http://prometheus:9090"
