"""OFAC SDN entry parsing and canonical field normalization."""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
from __future__ import annotations

import csv
import io
import logging
import xml.etree.ElementTree as ET
from typing import Any

logger = logging.getLogger(__name__)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _join_name(first: Any, last: Any) -> str | None:
    parts = [part for part in (_text(first), _text(last)) if part]
    return " ".join(parts) if parts else None


def _entry_from_fields(fields: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a JSON or XML-derived SDN entry."""
    first = _text(fields.get("firstName"))
    last = _text(fields.get("lastName"))
    whole = _text(fields.get("wholeName") or fields.get("sdnName"))
    name = _join_name(first, last) or whole
    if not name:
        return None
    programs_raw = fields.get("programs")
    if programs_raw is None:
        programs_raw = fields.get("programList")
    if isinstance(programs_raw, dict):
        programs_raw = programs_raw.get("program")
    programs = (
        [_text(program) for program in programs_raw] if isinstance(programs_raw, list) else []
    )
    return {
        "uid": _text(fields.get("uid")),
        "first_name": first,
        "last_name": last,
        "sdn_type": _text(fields.get("sdnType")),
        "programs": [program for program in programs if program],
        "title": _text(fields.get("title")),
        "remarks": _text(fields.get("remarks")),
        "akas": [aka for aka in (fields.get("akas") or []) if isinstance(aka, str) and aka.strip()],
        "citizenships": [
            citizenship
            for citizenship in (fields.get("citizenships") or [])
            if isinstance(citizenship, str) and citizenship.strip()
        ],
        "addresses": [],
        "source": "ofac_sdn",
    }


def _parse_json_entries(payload: Any) -> list[dict[str, Any]] | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    root = data if isinstance(data, dict) else payload
    sdn_list = root.get("sdnList")
    if not isinstance(sdn_list, dict):
        return None
    entries = sdn_list.get("sdnEntry") or []
    if not isinstance(entries, list):
        return None
    parsed_entries = [
        parsed
        for entry in entries
        if isinstance(entry, dict)
        if (parsed := _entry_from_fields(entry)) is not None
    ]
    return parsed_entries or None


def _xml_local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if tag.startswith("{") else tag


def _parse_xml_entries(raw: str) -> list[dict[str, Any]] | None:
    try:
        root = ET.fromstring(raw)  # nosec B314  # noqa: S314 — vetted HTTPS response; stdlib ET does not resolve external entities
    except ET.ParseError:
        logger.debug("legal_ofac_xml_parse_failed", exc_info=True)
        return None
    if _xml_local(root.tag) != "sdnList":
        return None
    out: list[dict[str, Any]] = []
    for entry in root:
        if _xml_local(entry.tag) != "sdnEntry":
            continue
        fields: dict[str, Any] = {}
        for child in entry:
            tag = _xml_local(child.tag)
            if tag == "programList":
                fields["programs"] = [_text(item.text) for item in child if _text(item.text)]
            elif tag == "akaList":
                fields["akas"] = _parse_aka_list(child)
            elif tag == "citizenshipList":
                fields["citizenships"] = [_text(item.text) for item in child if _text(item.text)]
            elif tag not in {
                "programList",
                "akaList",
                "addressList",
                "citizenshipList",
                "dateOfBirthList",
            }:
                fields[tag] = child.text
        parsed = _entry_from_fields(fields)
        if parsed is not None:
            out.append(parsed)
    return out or None


def _parse_aka_list(node: ET.Element) -> list[str]:
    names: list[str] = []
    for aka in node:
        if _xml_local(aka.tag) != "aka":
            continue
        first = next(
            (child.text for child in aka if _xml_local(child.tag) == "firstName"),
            None,
        )
        last = next(
            (child.text for child in aka if _xml_local(child.tag) == "lastName"),
            None,
        )
        name = _join_name(first, last)
        if name:
            names.append(name)
    return names


def _parse_csv_entries(raw: str) -> list[dict[str, Any]] | None:
    try:
        rows = [row for row in csv.reader(io.StringIO(raw)) if len(row) >= 2]
    except (csv.Error, UnicodeDecodeError):
        logger.debug("legal_ofac_csv_parse_failed", exc_info=True)
        return None
    out: list[dict[str, Any]] = []
    for row in rows:
        name = _text(row[1])
        if not name:
            continue
        country = _text(row[3]) if len(row) > 3 and row[3] != "-0-" else None
        remarks = _text(row[11]) if len(row) > 11 and row[11] != "-0-" else None
        out.append(
            {
                "uid": _text(row[0]),
                "first_name": name,
                "last_name": None,
                "sdn_type": None,
                "programs": [country] if country else [],
                "title": None,
                "remarks": remarks,
                "akas": [],
                "citizenships": [country] if country else [],
                "addresses": [],
                "source": "ofac_sdn",
            }
        )
    return out or None
