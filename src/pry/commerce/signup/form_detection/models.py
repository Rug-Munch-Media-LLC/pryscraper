"""Signup form detection — the data types a detected form is returned as.

Pure data holders; no parsing or classification lives here.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from dataclasses import dataclass, field

from .roles import ROLE_HIDDEN


@dataclass
class SignupField:
    """A single form control with a classified semantic role."""

    name: str
    role: str
    field_type: str
    tag: str
    value: str | None = None
    required: bool = False
    placeholder: str | None = None
    label: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "role": self.role,
            "field_type": self.field_type,
            "tag": self.tag,
            "value": self.value,
            "required": self.required,
            "placeholder": self.placeholder,
            "label": self.label,
        }


@dataclass
class SignupForm:
    """A detected form plus convenience accessors for signup-relevant fields."""

    action: str
    method: str
    fields: list[SignupField] = field(default_factory=list)
    form_index: int = 0
    page_url: str | None = None

    email_field: SignupField | None = None
    password_field: SignupField | None = None
    confirm_password_field: SignupField | None = None
    username_field: SignupField | None = None
    full_name_field: SignupField | None = None
    submit_button: SignupField | None = None

    def is_signup(self) -> bool:
        """True when the form looks like an account registration form.

        Requires an email field plus either a password field or a
        username/full-name field.
        """
        if self.email_field is None:
            return False
        if self.password_field is not None:
            return True
        return self.username_field is not None or self.full_name_field is not None

    def score(self) -> int:
        """Heuristic signup-likelihood score used to pick the best form."""
        total = 0
        if self.email_field is not None:
            total += 2
        if self.password_field is not None:
            total += 2
        if self.confirm_password_field is not None:
            total += 1
        if self.username_field is not None:
            total += 1
        if self.full_name_field is not None:
            total += 2
        if self.submit_button is not None:
            total += 1
        return total

    def hidden_fields(self) -> list[SignupField]:
        return [f for f in self.fields if f.role == ROLE_HIDDEN and f.name]

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "method": self.method,
            "form_index": self.form_index,
            "page_url": self.page_url,
            "fields": [f.to_dict() for f in self.fields],
            "email_field": self.email_field.name if self.email_field else None,
            "password_field": self.password_field.name if self.password_field else None,
            "username_field": self.username_field.name if self.username_field else None,
            "full_name_field": self.full_name_field.name if self.full_name_field else None,
            "submit_button": self.submit_button.name if self.submit_button else None,
        }


__all__ = ["SignupField", "SignupForm"]
