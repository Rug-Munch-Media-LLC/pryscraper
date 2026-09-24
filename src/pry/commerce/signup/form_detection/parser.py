"""Signup form detection — turning raw HTML into a control tree.

Walks the document with :class:`html.parser.HTMLParser`, keeping controls
and their enclosing form. Knows nothing about roles or field models.
"""

# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser

from .roles import _CONTROL_TAGS, _SKIP_TAGS


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


__all__ = ["_RawControl", "_RawForm", "_SignupFormParser"]
