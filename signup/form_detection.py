"""Signup form detection — find and classify registration forms in HTML.

Uses only the stdlib ``html.parser`` so the signup engine stays dependency-free
at the parsing layer. We collect every ``<form>`` together with its controls
(input/select/textarea/button) and label text, then classify each control into
a semantic role (email, password, username, full_name, ...) using name/id/type/
placeholder/aria/autocomplete heuristics plus the surrounding label text.

The public entry point is :func:`detect_signup_form`, which returns the
best-matching :class:`SignupForm` or ``None``.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin

# Tags whose content is not user-visible form text.
_SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "head", "svg"})

# Controls that can appear inside a form.
_CONTROL_TAGS = frozenset({"input", "select", "textarea", "button"})

# Role constants — used for field classification and signup scoring.
ROLE_EMAIL = "email"
ROLE_PASSWORD = "password"  # noqa: S105 - role label, not a credential
ROLE_CONFIRM_PASSWORD = "confirm_password"  # noqa: S105 - role label, not a credential
ROLE_USERNAME = "username"
ROLE_FULL_NAME = "full_name"
ROLE_SUBMIT = "submit"
ROLE_HIDDEN = "hidden"
ROLE_CHECKBOX = "checkbox"
ROLE_RADIO = "radio"
ROLE_CAPTCHA = "captcha"
ROLE_SELECT = "select"
ROLE_TEXTAREA = "textarea"
ROLE_TEXT = "text"


def _normalize(value: str | None) -> str:
    """Lowercase and collapse separators for fuzzy matching."""
    return re.sub(r"[\s_-]+", " ", (value or "").lower()).strip()


def classify_role(
    *,
    name: str = "",
    control_id: str = "",
    field_type: str = "text",
    tag: str = "input",
    placeholder: str = "",
    aria_label: str = "",
    autocomplete: str = "",
    label: str = "",
) -> str:
    """Classify a form control into a semantic role.

    Order matters: explicit type hints (password/email/submit) win over
    autocomplete attributes, which win over name/id/label-text heuristics.
    """
    ctype = field_type.lower()
    tag = tag.lower()
    haystack = _normalize(
        " ".join([name, control_id, placeholder, aria_label, autocomplete, label])
    )

    if ctype == "password":
        if any(word in haystack for word in ("confirm", "repeat", "again", "match")):
            return ROLE_CONFIRM_PASSWORD
        return ROLE_PASSWORD
    if ctype == "email":
        return ROLE_EMAIL
    if tag == "button" or ctype == "submit":
        return ROLE_SUBMIT
    if ctype == "hidden":
        return ROLE_HIDDEN
    if ctype == "checkbox":
        return ROLE_CHECKBOX
    if ctype == "radio":
        return ROLE_RADIO
    if ctype == "file":
        return ROLE_TEXT

    ac = autocomplete.lower()
    if ac == "email":
        return ROLE_EMAIL
    if ac == "username":
        return ROLE_USERNAME
    if ac == "name":
        return ROLE_FULL_NAME
    if ac == "password":
        return ROLE_PASSWORD
    if ac == "new-password":
        return ROLE_PASSWORD

    if tag == "select":
        return ROLE_SELECT
    if tag == "textarea":
        return ROLE_TEXTAREA

    # Name/id/placeholder/label-text heuristics.
    if "email" in haystack or "mail" in haystack:
        return ROLE_EMAIL
    if "pass" in haystack or "pwd" in haystack:
        return ROLE_PASSWORD
    if (
        "username" in haystack
        or "screenname" in haystack
        or "screen name" in haystack
        or "handle" in haystack
        or "login" in haystack
        or "user" in haystack
    ):
        return ROLE_USERNAME
    if "fullname" in haystack or "full name" in haystack:
        return ROLE_FULL_NAME
    if (
        "name" in haystack
        and "first" not in haystack
        and "last" not in haystack
        and "company" not in haystack
        and "middle" not in haystack
    ):
        return ROLE_FULL_NAME
    if "captcha" in haystack or "recaptcha" in haystack:
        return ROLE_CAPTCHA
    return ROLE_TEXT


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


@dataclass
class _RawControl:
    """Intermediate control representation collected by the parser."""

    tag: str
    attrs: dict[str, str]
    text: str = ""
    label: str | None = None


@dataclass
class _RawForm:
    """Intermediate form representation collected by the parser."""

    action: str = ""
    method: str = "post"
    controls: list[_RawControl] = field(default_factory=list)
    label_for: dict[str, str] = field(default_factory=dict)


class _SignupFormParser(HTMLParser):
    """HTMLParser subclass that collects forms and their controls."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.forms: list[_RawForm] = []
        self._form_stack: list[int] = []
        self._skip_depth = 0
        self._in_label = False
        self._label_text_parts: list[str] = []
        self._label_control: int | None = None  # index of control inside current label
        self._current_label_for = ""
        self._pending_control: _RawControl | None = None
        self._pending_label: str | None = None  # label that ended just before a control
        self._last_control_idx: int = -1

    # -- helpers -----------------------------------------------------------

    @property
    def _current_form(self) -> _RawForm | None:
        if not self._form_stack:
            return None
        return self.forms[self._form_stack[-1]]

    def _attr_dict(self, attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {key: (value or "") for key, value in attrs}

    def _finalize_pending_control(self) -> None:
        """Commit a control whose text content just closed (select/textarea/button)."""
        control = self._pending_control
        if control is None:
            return
        self._pending_control = None
        self._add_control(control)

    def _add_control(self, control: _RawControl) -> None:
        form = self._current_form
        if form is None:
            return

        # Attach label text in priority order:
        # 1. control wrapped inside a label (collected on </label>)
        # 2. label[for=id]
        # 3. preceding label that ended without wrapping a control
        control_id = control.attrs.get("id", "")
        if control.label is None and control_id and control_id in form.label_for:
            control.label = form.label_for[control_id]
            self._pending_label = None
        elif control.label is None and self._pending_label is not None:
            control.label = self._pending_label
            self._pending_label = None

        form.controls.append(control)
        self._last_control_idx = len(form.controls) - 1
        # A control inside a label consumes the label.
        if self._in_label and self._label_control is None:
            self._label_control = self._last_control_idx

    # -- parser callbacks -------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return

        a = self._attr_dict(attrs)
        if tag == "form":
            form = _RawForm(action=a.get("action", ""), method=a.get("method", "post"))
            self.forms.append(form)
            self._form_stack.append(len(self.forms) - 1)
            return

        if tag == "label":
            self._in_label = True
            self._label_text_parts = []
            self._label_control = None
            self._current_label_for = a.get("for", "")
            return

        if self._form_stack and tag in _CONTROL_TAGS:
            if tag == "input":
                # Inputs are void elements: record immediately.
                self._add_control(_RawControl(tag=tag, attrs=a))
            else:
                self._pending_control = _RawControl(tag=tag, attrs=a)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return

        if tag == "form":
            if self._form_stack:
                self._form_stack.pop()
            return

        if tag == "label":
            label_text = " ".join(" ".join(self._label_text_parts).split())
            form = self._current_form
            if form is not None and label_text:
                if self._current_label_for:
                    form.label_for[self._current_label_for] = label_text
                if self._label_control is not None:
                    controls = form.controls
                    if controls and controls[self._label_control].label is None:
                        controls[self._label_control].label = label_text
                else:
                    # Label that preceded (did not wrap) a control.
                    self._pending_label = label_text
            self._in_label = False
            self._label_text_parts = []
            self._label_control = None
            self._current_label_for = ""
            return

        if tag in _CONTROL_TAGS:
            self._finalize_pending_control()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_label:
            self._label_text_parts.append(data)
        elif self._pending_control is not None:
            self._pending_control.text += data


def _build_form(raw: _RawForm, index: int, page_url: str | None) -> SignupForm | None:
    """Convert a raw parsed form into a classified SignupForm."""
    if not raw.controls:
        return None

    fields: list[SignupField] = []
    for control in raw.controls:
        role = classify_role(
            name=control.attrs.get("name", ""),
            control_id=control.attrs.get("id", ""),
            field_type=control.attrs.get("type", "text" if control.tag == "input" else control.tag),
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
                field_type=control.attrs.get(
                    "type", "text" if control.tag == "input" else control.tag
                ),
                tag=control.tag,
                value=control.attrs.get("value"),
                required=control.attrs.get("required") is not None,
                placeholder=control.attrs.get("placeholder"),
                label=control.label or None,
            )
        )

    form = SignupForm(
        action=urljoin(page_url, raw.action) if page_url else raw.action,
        method=(raw.method or "post").lower(),
        fields=fields,
        form_index=index,
        page_url=page_url,
    )

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
    return form


def detect_signup_form(html: str, url: str | None = None) -> SignupForm | None:
    """Detect the best signup form in an HTML document.

    Args:
        html: The raw HTML of the page.
        url: The page URL, used to resolve relative form actions.

    Returns:
        The highest-scoring :class:`SignupForm` that qualifies as a signup
        form, or ``None`` if no registration form is found.
    """
    parser = _SignupFormParser()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 - malformed HTML must never crash detection
        return None

    forms = [_build_form(raw, index, url) for index, raw in enumerate(parser.forms)]
    candidates = [form for form in forms if form is not None and form.is_signup()]
    if not candidates:
        return None
    return max(candidates, key=lambda form: form.score())
