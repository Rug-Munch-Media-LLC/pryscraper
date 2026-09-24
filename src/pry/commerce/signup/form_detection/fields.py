"""Signup form detection — assembling parsed controls into a form.

Maps controls to field types, assigns roles, and drops anything that is not
a usable input. The seam between the parser and the public model.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urljoin

from .models import SignupField, SignupForm
from .roles import (
    ROLE_CONFIRM_PASSWORD,
    ROLE_EMAIL,
    ROLE_FULL_NAME,
    ROLE_PASSWORD,
    ROLE_SUBMIT,
    ROLE_USERNAME,
    classify_role,
)

if TYPE_CHECKING:
    from .parser import _RawControl, _RawForm


def _control_field_type(control: _RawControl) -> str:
    """Effective field type for a raw control."""
    return control.attrs.get("type", "text" if control.tag == "input" else control.tag)


def _build_fields(raw: _RawForm) -> list[SignupField]:
    """Classify each raw control into a SignupField."""
    fields: list[SignupField] = []
    for control in raw.controls:
        role = classify_role(
            name=control.attrs.get("name", ""),
            control_id=control.attrs.get("id", ""),
            field_type=_control_field_type(control),
            tag=control.tag,
            placeholder=control.attrs.get("placeholder", ""),
            aria_label=control.attrs.get("aria-label", ""),
            autocomplete=control.attrs.get("autocomplete", ""),
            label=control.label or control.text or "",
        )
        fields.append(
            SignupField(
                name=control.attrs.get("name", ""),
                role=role,
                field_type=_control_field_type(control),
                tag=control.tag,
                value=control.attrs.get("value"),
                required=control.attrs.get("required") is not None,
                placeholder=control.attrs.get("placeholder"),
                label=control.label or None,
            )
        )
    return fields


def _assign_role_fields(form: SignupForm, fields: list[SignupField]) -> None:
    """Bind the first field of each well-known role to its form slot."""
    for field_ in fields:
        if field_.role == ROLE_EMAIL and form.email_field is None:
            form.email_field = field_
        elif field_.role == ROLE_PASSWORD and form.password_field is None:
            form.password_field = field_
        elif field_.role == ROLE_CONFIRM_PASSWORD and form.confirm_password_field is None:
            form.confirm_password_field = field_
        elif field_.role == ROLE_USERNAME and form.username_field is None:
            form.username_field = field_
        elif field_.role == ROLE_FULL_NAME and form.full_name_field is None:
            form.full_name_field = field_
        elif field_.role == ROLE_SUBMIT and form.submit_button is None:
            form.submit_button = field_


def _build_form(raw: _RawForm, index: int, page_url: str | None) -> SignupForm | None:
    """Convert a raw parsed form into a classified SignupForm."""
    if not raw.controls:
        return None

    fields = _build_fields(raw)

    form = SignupForm(
        action=urljoin(page_url, raw.action) if page_url else raw.action,
        method=(raw.method or "post").lower(),
        fields=fields,
        form_index=index,
        page_url=page_url,
    )
    _assign_role_fields(form, fields)
    return form


__all__ = ["_build_form"]
